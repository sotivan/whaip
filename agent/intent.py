"""
WHAIP – Intent classifier

Before acting, every voice transcription passes through here.
This layer:
  1. Decides if the transcription is a real user command or background noise/audio
  2. Interprets what the user actually means (handles slang, partial phrases, context)
  3. Returns a clean intent or None if it should be ignored

Uses a fast, cheap Claude call with minimal context.
"""

import logging
from typing import Optional

logger = logging.getLogger("whaip.intent")

CLASSIFIER_PROMPT = """You are an intent classifier for WHAIP, a voice-controlled browser assistant.

The user speaks directly to you to control their browser. When they say something, they want YOU to do it.
Transcription context:
URL: {url}
Page title: {title}
Last command: {last_command}

Raw transcription: "{transcription}"

Your task: decide if this is a real user command or background audio/noise.

COMMANDS (is_command=true) — any of these patterns:
- Imperative verbs directed at the browser: pulsa, haz clic, navega, busca, abre, cierra, salta, pausa, reproduce, pon, ponme, escribe, rellena, manda, envía, descarga, sube, compra, acepta, rechaza, vuelve, avanza, retrocede, scroll, baja, sube, maximiza, minimiza, recarga
- Search requests: "busca X", "buscar X en Y", "quiero ver X"
- Navigation: "ve a", "abre", "navega a", "pon X en YouTube"
- Page interaction: "pulsa el botón de X", "haz clic en X", "selecciona X", "rellena el campo X con Y"
- Corrections/meta: "no, espera", "para", "cancela", "ignora eso", "no hagas eso", "mejor X"
- Even if poorly transcribed: "alta el anuncio" = "salta el anuncio", "avarle" = "lavarle"

BACKGROUND AUDIO (is_command=false) — only if clearly NOT addressed to you:
- Song lyrics (rhyming, musical phrasing)
- Ad slogans or TV dialogue (third-person narrative, product names)
- Pure noise: "en", "1, 11,", numbers only, isolated syllables
- Clearly not a browser instruction and no plausible interpretation as one

CRITICAL RULES:
- When in doubt → is_command=true. It's better to attempt an action than to ignore the user.
- If transcription contains ANY imperative verb → is_command=true, confidence ≥ 0.7
- "no ignores", "no hagas caso", "espera", "para" → is_command=true (user correcting/pausing)
- intent: always rewrite in clean Spanish. Keep the user's actual goal.
- Use page context to resolve ambiguity: "desde el fin del mundo" on YouTube → "buscar canción 'Desde el fin del mundo' de Duki"
- EMAIL DICTATION: Users speak emails character by character. Common patterns:
  * "ivan punto somo punto 111 arroba gmail punto com" → "ivan.somo.111@gmail.com"
  * "arroba" = @, "punto" = . (in email context), "guion" = -, "guion bajo" = _
  * Whisper often mishears email domains: "jemail"→"gmail", "jotmail"→"hotmail", "yaoo"→"yahoo"
  * If transcription looks like a spoken email, reconstruct the correct email address in the intent.
- Reply ONLY with the JSON object, nothing else.

{{
  "is_command": true/false,
  "intent": "clean description of what the user wants, in Spanish",
  "confidence": 0.0-1.0,
  "reason": "one line explanation"
}}"""


class IntentClassifier:

    def __init__(self, config: dict):
        self.config  = config
        self.enabled = bool(config.get("anthropic_api_key", "").strip())
        self._client = None
        self._last_command: str = ""
        self._current_url: str = ""
        self._current_title: str = ""

    def setup(self) -> None:
        if not self.enabled:
            return
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.config["anthropic_api_key"])
            logger.info("IntentClassifier ready.")
        except Exception as exc:
            logger.warning("IntentClassifier disabled: %s", exc)
            self.enabled = False

    def update_context(self, url: str = "", title: str = "") -> None:
        if url:   self._current_url   = url
        if title: self._current_title = title

    # Verbs that almost certainly mean the user is giving a command
    _COMMAND_VERBS = {
        "pulsa", "haz", "navega", "busca", "abre", "cierra", "salta", "pausa",
        "reproduce", "pon", "ponme", "escribe", "rellena", "manda", "envía",
        "envia", "descarga", "sube", "compra", "acepta", "rechaza", "vuelve",
        "avanza", "retrocede", "scroll", "maximiza", "minimiza", "recarga",
        "buscar", "abrir", "cerrar", "saltar", "pausar", "poner", "escribir",
        "rellenar", "mandar", "descargar", "comprar", "aceptar", "rechazar",
        "volver", "recargar", "quiero", "muéstrame", "muestrame", "dime",
        "llévame", "llevame", "ir", "ve", "para", "stop", "cancela", "cancel",
    }

    async def classify(self, transcription: str) -> Optional[str]:
        """
        Returns the clean intent string if this is a real command, else None.
        Fast path: if no Claude, use simple heuristics.
        """
        if not transcription or len(transcription.strip()) < 3:
            return None

        words = transcription.lower().split()

        # Fast heuristic: too short or pure noise
        if len(words) < 2 and transcription.lower() not in ("sí", "si", "no", "para", "espera", "stop"):
            logger.debug("Ignored (too short): %s", transcription)
            return None

        # Fast-path: if starts with a known command verb → skip classifier, always a command
        if words[0] in self._COMMAND_VERBS or (len(words) > 1 and words[1] in self._COMMAND_VERBS):
            logger.info("Intent [fast-path] ✓ → %s", transcription)
            self._last_command = transcription
            return transcription

        if not self.enabled or not self._client:
            # No Claude → pass everything through (degraded mode)
            return transcription

        try:
            import asyncio, json, re
            prompt = CLASSIFIER_PROMPT.format(
                url=self._current_url or "desconocida",
                title=self._current_title or "desconocida",
                last_command=self._last_command or "ninguno",
                transcription=transcription,
            )

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.messages.create(
                    model="claude-haiku-4-5-20251001",   # fast + cheap
                    max_tokens=150,
                    messages=[{"role": "user", "content": prompt}],
                ),
            )

            raw = response.content[0].text.strip()
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw).strip()
            data = json.loads(raw)

            is_cmd    = data.get("is_command", False)
            intent    = data.get("intent", transcription)
            confidence = data.get("confidence", 0.0)
            reason    = data.get("reason", "")

            logger.info(
                "Intent [%.0f%%] %s → %s (%s)",
                confidence * 100,
                "✓" if is_cmd else "✗",
                intent if is_cmd else "IGNORED",
                reason,
            )

            if not is_cmd or confidence < 0.35:
                return None

            self._last_command = intent
            return intent

        except Exception as exc:
            logger.error("Intent classification error: %s", exc)
            # On error, pass through to avoid blocking the user
            return transcription
