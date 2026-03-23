"""
WHAIP – ElevenLabs TTS integration
Converts agent responses to speech.
Disabled silently if elevenlabs_api_key or elevenlabs_voice_id are empty.
"""

import logging
from .base import BaseIntegration

logger = logging.getLogger("whaip.integrations.elevenlabs")

class ElevenLabsClient(BaseIntegration):

    def __init__(self, config: dict):
        super().__init__(config, required_keys=["elevenlabs_api_key", "elevenlabs_voice_id"])
        self._client   = None   # elevenlabs.ElevenLabs instance
        self._voice_id = config.get("elevenlabs_voice_id", "")

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def setup(self):
        """Initialize ElevenLabs client."""
        # TODO: if not self.enabled → return
        # TODO: from elevenlabs import ElevenLabs
        # TODO: self._client = ElevenLabs(api_key=self.config['elevenlabs_api_key'])
        pass

    def teardown(self):
        """No persistent resources to release."""
        pass

    # ── Public API ─────────────────────────────────────────────────────────

    async def speak(self, text: str):
        """
        Convert `text` to speech and play it through the system audio output.
        No-op if disabled or text is empty.
        """
        # TODO: if not self.enabled or not text → return
        # TODO: audio = self._client.text_to_speech.convert(voice_id=..., text=text)
        # TODO: play audio bytes with sounddevice or subprocess (platform-dependent)
        pass

    async def speak_stream(self, text: str):
        """
        Streaming TTS: play audio as chunks arrive to reduce latency.
        No-op if disabled.
        """
        # TODO: use self._client.text_to_speech.stream(voice_id=..., text=text)
        # TODO: pipe chunks to audio output in real-time
        pass
