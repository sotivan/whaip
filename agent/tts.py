"""
WHAIP – Text-to-speech module

Priority:
  1. ElevenLabs (configured via elevenlabs_api_key + elevenlabs_voice_id)
  2. pyttsx3 (offline, cross-platform)
  3. macOS `say` command (subprocess fallback)
  4. Silent (logs the text if nothing works)

The agent calls speak() and doesn't care which backend runs.
"""

import asyncio
import logging
import subprocess
import tempfile
import os
from typing import Optional

logger = logging.getLogger("whaip.tts")


class TTSClient:

    def __init__(self, config: dict):
        self.config   = config
        self._api_key  = config.get("elevenlabs_api_key", "").strip()
        self._voice_id = config.get("elevenlabs_voice_id", "").strip()
        self._backend  = None   # resolved on first speak()

    def _resolve_backend(self) -> str:
        if self._api_key and self._voice_id:
            try:
                import elevenlabs  # noqa
                return "elevenlabs"
            except ImportError:
                logger.warning("elevenlabs package not installed – trying pip install...")
                try:
                    subprocess.run(
                        ["pip", "install", "elevenlabs", "-q"],
                        check=True, capture_output=True
                    )
                    return "elevenlabs"
                except Exception:
                    logger.warning("Could not install elevenlabs, falling back.")

        try:
            import pyttsx3  # noqa
            return "pyttsx3"
        except ImportError:
            pass

        # macOS / Linux fallback
        if subprocess.run(["which", "say"], capture_output=True).returncode == 0:
            return "say"
        if subprocess.run(["which", "espeak"], capture_output=True).returncode == 0:
            return "espeak"

        return "silent"

    async def speak(self, text: str) -> None:
        """Speak text asynchronously. Never raises."""
        if not text:
            return

        if self._backend is None:
            self._backend = self._resolve_backend()
            logger.info("TTS backend: %s", self._backend)

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._speak_sync, text)
        except Exception as exc:
            logger.error("TTS error: %s", exc)

    def _speak_sync(self, text: str) -> None:
        if self._backend == "elevenlabs":
            self._speak_elevenlabs(text)
        elif self._backend == "pyttsx3":
            self._speak_pyttsx3(text)
        elif self._backend == "say":
            subprocess.run(["say", "-v", "Mónica", text], check=False)
        elif self._backend == "espeak":
            subprocess.run(["espeak", "-v", "es", text], check=False)
        else:
            logger.info("[TTS silent] %s", text)

    def _speak_elevenlabs(self, text: str) -> None:
        from elevenlabs.client import ElevenLabs
        from elevenlabs import play

        client = ElevenLabs(api_key=self._api_key)
        audio = client.text_to_speech.convert(
            voice_id=self._voice_id,
            text=text,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )
        play(audio)

    def _speak_pyttsx3(self, text: str) -> None:
        import pyttsx3
        engine = pyttsx3.init()
        # Try to pick a Spanish voice
        for voice in engine.getProperty("voices"):
            if "es" in (voice.languages or []) or "spanish" in voice.name.lower():
                engine.setProperty("voice", voice.id)
                break
        engine.setProperty("rate", 170)
        engine.say(text)
        engine.runAndWait()
        engine.stop()

    @property
    def enabled(self) -> bool:
        if self._backend is None:
            self._backend = self._resolve_backend()
        return self._backend != "silent"
