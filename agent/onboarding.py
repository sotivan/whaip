"""
WHAIP – First-run onboarding interview

Two modes:
  - Voice (ElevenLabs configured): natural conversation via TTS + Whisper
  - Form  (no ElevenLabs):         UI form shown in the sidebar

Runs once on first launch. Saves answers to UserMemory.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main import AgentLoop

logger = logging.getLogger("whaip.onboarding")

# ── Questions ────────────────────────────────────────────────────────────────

QUESTIONS = [
    {
        "key":   "name",
        "voice": "Para empezar, ¿cómo te llamas?",
        "label": "¿Cómo te llamas?",
        "hint":  "Tu nombre",
        "type":  "text",
    },
    {
        "key":   "city",
        "voice": "¿En qué ciudad y país vives?",
        "label": "Ciudad y país",
        "hint":  "Ej: Madrid, España",
        "type":  "text",
    },
    {
        "key":   "home_address",
        "voice": "¿Cuál es tu dirección habitual para recibir pedidos? Dime calle, número y ciudad.",
        "label": "Dirección de entrega habitual",
        "hint":  "Calle, número, ciudad",
        "type":  "text",
    },
    {
        "key":   "food_preferences",
        "voice": "¿Qué tipo de comida sueles pedir? Por ejemplo: pizza, sushi, hamburguesas...",
        "label": "¿Qué comida sueles pedir?",
        "hint":  "Pizza, sushi, chino, hamburgesas...",
        "type":  "text",
    },
    {
        "key":   "food_delivery_platforms",
        "voice": "¿Qué apps de delivery usas habitualmente? Por ejemplo: Glovo, Just Eat, Uber Eats...",
        "label": "Apps de delivery",
        "hint":  "Glovo, Just Eat, Uber Eats...",
        "type":  "text",
        "options": ["Glovo", "Just Eat", "Uber Eats", "Deliveroo", "Domino's", "Otra"],
    },
    {
        "key":   "streaming_platforms",
        "voice": "¿Qué plataformas de entretenimiento usas? Netflix, Spotify, YouTube...",
        "label": "Plataformas de entretenimiento",
        "hint":  "Netflix, Spotify, YouTube, Disney+...",
        "type":  "text",
        "options": ["Netflix", "Spotify", "YouTube", "Disney+", "HBO Max", "Apple TV+", "Amazon Prime Video", "Otra"],
    },
    {
        "key":   "shopping_platforms",
        "voice": "¿Dónde sueles comprar online? Amazon, El Corte Inglés, Zalando...",
        "label": "Tiendas online habituales",
        "hint":  "Amazon, Zalando, El Corte Inglés...",
        "type":  "text",
        "options": ["Amazon", "El Corte Inglés", "Zalando", "Shein", "Zara", "AliExpress", "Otra"],
    },
]

SETUP_TIPS = [
    "Inicia sesión en tus plataformas favoritas para que pueda actuar en tu nombre.",
    "Añade tus métodos de pago en las tiendas que uses habitualmente.",
    "Guarda tus páginas favoritas como marcadores.",
    "Cuanto más contexto tengas guardado, más rápido y barato será cada tarea.",
]


# ── Flow ─────────────────────────────────────────────────────────────────────

class OnboardingFlow:

    def __init__(self, agent: "AgentLoop"):
        self.agent   = agent
        self._answers: dict = {}   # key → answer, filled by UI form if used

    async def run(self) -> None:
        has_elevenlabs = bool(self.agent.config.get("elevenlabs_api_key", "").strip())
        logger.info("Onboarding start (elevenlabs=%s)", has_elevenlabs)

        await self.agent.broadcast({"type": "onboarding:start"})

        if has_elevenlabs:
            await self._run_voice()
        else:
            await self._run_form()

        # Save home location if geolocation available
        try:
            geo = await self.agent.request_geolocation(timeout=5.0)
            if geo and geo.get("lat"):
                self.agent.memory.set_home_location(geo["lat"], geo["lng"])
                logger.info("Home location saved: %.4f, %.4f", geo["lat"], geo["lng"])
        except Exception:
            pass

        # Post-onboarding tips
        name = self.agent.memory.get("name", "")
        if has_elevenlabs:
            await self.agent.say(
                f"{'¡Perfecto, ' + name + '!' if name else '¡Perfecto!'} "
                "Ya tengo tu perfil. "
                "Te recomiendo que entres en tus plataformas favoritas e inicies sesión, "
                "y que añadas tus métodos de pago. "
                "Cuanto más contexto tenga, mejor y más barato funcionaré."
            )

        await self.agent.broadcast({"type": "onboarding:tips", "tips": SETUP_TIPS})
        self.agent.memory.mark_onboarding_done()
        await self.agent.broadcast({"type": "onboarding:done", "name": name})
        logger.info("Onboarding done for: %s", name or "unknown")

    # ── Voice mode ────────────────────────────────────────────────────────

    async def _run_voice(self) -> None:
        await self.agent.say(
            "Hola, soy WHAIP, tu agente de navegación personal. "
            "Antes de empezar quiero conocerte un poco. "
            "Son solo unas preguntas rápidas."
        )
        await asyncio.sleep(0.3)

        for q in QUESTIONS:
            await self.agent.broadcast({
                "type": "onboarding:question",
                "key":  q["key"],
                "text": q["label"],
            })
            answer = await self.agent.ask_and_wait(q["voice"], timeout=25.0)
            if answer and len(answer.strip()) > 1:
                self.agent.memory.set(q["key"], answer.strip())
                logger.info("Voice onboarding [%s] = %s", q["key"], answer.strip()[:60])
            else:
                await self.agent.say("Sin problema, me lo dices cuando quieras.")
            await asyncio.sleep(0.2)

    # ── Form mode (no ElevenLabs) ─────────────────────────────────────────

    async def _run_form(self) -> None:
        """Send form to Electron; wait for onboarding:answers message."""
        await self.agent.broadcast({
            "type":      "onboarding:form",
            "questions": QUESTIONS,
        })

        # Wait up to 10 min for the user to fill in the form
        deadline = asyncio.get_event_loop().time() + 600
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.5)
            if self.agent.memory.is_onboarding_done():
                return      # answers already saved by handle_incoming
            # Check if all required keys are filled
            filled = all(self.agent.memory.get(q["key"]) for q in QUESTIONS[:3])  # name+city+address
            if filled:
                return
        # Timeout — continue anyway
        logger.warning("Onboarding form timeout, proceeding with partial data")
