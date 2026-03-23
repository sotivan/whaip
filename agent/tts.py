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
import os
import subprocess
import tempfile
import threading

logger = logging.getLogger("whaip.tts")

# Backends tried in order. Each is tried at startup; first that works wins.
_BACKENDS = ["elevenlabs", "pyttsx3", "say", "espeak", "silent"]


class TTSClient:

    def __init__(self, config: dict, memory=None):
        self._api_key  = config.get("elevenlabs_api_key", "").strip()
        self._voice_id = config.get("elevenlabs_voice_id", "").strip()
        self._memory   = memory          # UserMemory instance for persistent voice pref
        self._backend  = None
        self._lock     = threading.Lock()  # one utterance at a time

    # ── Voice ID (can be overridden by memory) ─────────────────────────────

    def _get_voice_id(self) -> str:
        if self._memory:
            saved = self._memory.get("elevenlabs_voice_id")
            if saved:
                return saved
        return self._voice_id

    def set_voice(self, voice_id: str) -> None:
        """Change ElevenLabs voice and persist it."""
        self._voice_id = voice_id
        if self._memory:
            self._memory.set("elevenlabs_voice_id", voice_id)
        logger.info("TTS voice changed to: %s", voice_id)

    # ── Backend resolution ─────────────────────────────────────────────────

    def _resolve_backend(self) -> str:
        if self._api_key and self._get_voice_id():
            try:
                from elevenlabs.client import ElevenLabs  # noqa
                logger.info("TTS backend: elevenlabs")
                return "elevenlabs"
            except ImportError:
                logger.warning("elevenlabs package not installed, falling back.")

        try:
            import pyttsx3  # noqa
            logger.info("TTS backend: pyttsx3")
            return "pyttsx3"
        except ImportError:
            pass

        if subprocess.run(["which", "say"], capture_output=True).returncode == 0:
            logger.info("TTS backend: macOS say")
            return "say"

        if subprocess.run(["which", "espeak"], capture_output=True).returncode == 0:
            logger.info("TTS backend: espeak")
            return "espeak"

        logger.warning("TTS backend: silent (no TTS available)")
        return "silent"

    # ── Public API ─────────────────────────────────────────────────────────

    async def speak(self, text: str) -> None:
        """Speak text. Waits for previous utterance to finish (no overlapping)."""
        if not text:
            return
        if self._backend is None:
            self._backend = self._resolve_backend()

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._speak_blocking, text)

    def _speak_blocking(self, text: str) -> None:
        """Runs in thread pool. Lock ensures no two utterances overlap."""
        with self._lock:
            try:
                self._speak_sync(text)
            except Exception as exc:
                logger.error("TTS [%s] failed: %s — trying fallback", self._backend, exc)
                self._speak_fallback(text)

    def _speak_sync(self, text: str) -> None:
        if self._backend == "elevenlabs":
            self._speak_elevenlabs(text)
        elif self._backend == "pyttsx3":
            self._speak_pyttsx3(text)
        elif self._backend == "say":
            subprocess.run(["say", text], check=True)
        elif self._backend == "espeak":
            subprocess.run(["espeak", "-v", "es", text], check=True)
        else:
            logger.info("[TTS silent] %s", text)

    def _speak_fallback(self, text: str) -> None:
        """Last-resort: macOS say, then silent."""
        try:
            subprocess.run(["say", text], check=True, timeout=30)
        except Exception:
            logger.info("[TTS silent fallback] %s", text)

    def _speak_elevenlabs(self, text: str) -> None:
        from elevenlabs.client import ElevenLabs

        client = ElevenLabs(api_key=self._api_key)
        audio_gen = client.text_to_speech.convert(
            voice_id=self._get_voice_id(),
            text=text,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )
        # Collect generator into bytes
        audio_bytes = b"".join(audio_gen)

        # Play: prefer afplay (Mac built-in), then mpv, then elevenlabs.play()
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_bytes)
            tmp = f.name
        try:
            if subprocess.run(["which", "afplay"], capture_output=True).returncode == 0:
                subprocess.run(["afplay", tmp], check=True)
            elif subprocess.run(["which", "mpv"], capture_output=True).returncode == 0:
                subprocess.run(["mpv", "--no-video", "--really-quiet", tmp], check=True)
            elif subprocess.run(["which", "ffplay"], capture_output=True).returncode == 0:
                subprocess.run(["ffplay", "-nodisp", "-autoexit", tmp], check=True,
                               capture_output=True)
            else:
                from elevenlabs import play
                play(audio_bytes)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def _speak_pyttsx3(self, text: str) -> None:
        import pyttsx3
        engine = pyttsx3.init()
        for voice in engine.getProperty("voices"):
            name = (voice.name or "").lower()
            if "mónica" in name or "monica" in name or "spanish" in name:
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
