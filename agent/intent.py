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

CLASSIFIER_PROMPT = """You are an intent classifier for a voice-controlled browser assistant.

The user speaks in Spanish (or sometimes English) to control their browser.
You receive a raw voice transcription that may contain:
- A real browser command ("pon una canción de duki", "busca vuelos a madrid", "salta el anuncio")
- Garbled speech or mishearing ("avarle el móvil a mamá", "naladro", "alta el anuncio" = "salta el anuncio")
- Background audio from the browser (ads, music lyrics, YouTube audio)
- Incomplete words or noise ("en", "1, 11,", "baby figure...")

Current browser context:
URL: {url}
Page title: {title}
Last user command: {last_command}

Raw transcription: "{transcription}"

Respond with a JSON object:
{{
  "is_command": true/false,
  "intent": "clean natural language description of what the user wants, in Spanish",
  "confidence": 0.0-1.0,
  "reason": "why you classified it this way"
}}

Rules:
- is_command=false if: transcription sounds like audio playing in background, is too short/meaningless, is clearly garbled noise
- is_command=true if: user is clearly asking the browser to do something, even if transcription is imperfect
- intent: rewrite the command cleanly. "avarle el móvil" → "lavarle el móvil". "alta el anuncio" → "salta el anuncio". "a tope" → "al máximo"
- Use page context: if user says "desde el fin del mundo" while on YouTube, intent is "buscar canción 'Desde el fin del mundo' de Duki"
- confidence below 0.5 → is_command=false
- ONLY return the JSON object, nothing else."""


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

    async def classify(self, transcription: str) -> Optional[str]:
        """
        Returns the clean intent string if this is a real command, else None.
        Fast path: if no Claude, use simple heuristics.
        """
        if not transcription or len(transcription.strip()) < 3:
            return None

        # Fast heuristic: too short or pure noise
        words = transcription.split()
        if len(words) < 2 and transcription not in ("sí", "no", "para", "espera"):
            logger.debug("Ignored (too short): %s", transcription)
            return None

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

            if not is_cmd or confidence < 0.5:
                return None

            self._last_command = intent
            return intent

        except Exception as exc:
            logger.error("Intent classification error: %s", exc)
            # On error, pass through to avoid blocking the user
            return transcription
