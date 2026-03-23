"""
WHAIP – Voice listener module

Captures microphone audio continuously and transcribes speech using OpenAI
Whisper running fully local (no API key required).

Architecture
────────────
  sounddevice callback (C thread)
        │  chunks via threading.Queue
        ▼
  _capture_thread  (daemon thread)
    └─ VAD → assembles utterances → puts numpy arrays in _raw_queue
        │
        ▼
  _bridge_loop  (asyncio task)
    └─ drains _raw_queue → run_in_executor(_transcribe) → _text_queue

Public callers use get_latest() or listen_once() to read from _text_queue.

Disabled silently if `whisper` or `sounddevice` cannot be imported, or if
the microphone cannot be opened.
"""

import asyncio
import logging
import queue
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger("whaip.voice")

# ── Audio constants ────────────────────────────────────────────────────────
SAMPLE_RATE    = 16_000          # Hz – Whisper's native rate
CHANNELS       = 1
DTYPE          = "float32"
BLOCK_SAMPLES  = 480             # 30 ms per sounddevice callback block

# ── VAD constants ──────────────────────────────────────────────────────────
RMS_THRESHOLD      = 0.035       # below → silence (higher = less background noise)
SPEECH_ONSET_BLOCKS = 4          # consecutive loud blocks to start recording
SILENCE_END_BLOCKS  = 25         # ~0.75 s of silence to end utterance
MIN_SPEECH_BLOCKS   = 15         # ~0.45 s minimum to avoid transcribing noise


class VoiceListener:
    """
    Continuously listens to the default microphone and exposes transcriptions
    via an asyncio Queue.  All heavy work runs off the event loop.
    """

    def __init__(self, config: dict):
        self.config   = config
        self.enabled  = False

        agent_cfg = config.get("agent", {})
        self._model_name: str = agent_cfg.get("whisper_model", "base")
        self._language: str   = agent_cfg.get("language", "es")

        self._model       = None                   # whisper.Model
        self._raw_queue:  queue.Queue  = queue.Queue()   # audio arrays from thread
        self._text_queue: asyncio.Queue = asyncio.Queue()  # transcriptions for callers

        self._stop_event  = threading.Event()
        self._capture_thread: Optional[threading.Thread] = None
        self._bridge_task: Optional[asyncio.Task]        = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def setup(self) -> None:
        """
        Load Whisper and start the microphone listener.
        Silently disables itself on any error so the app boots regardless.
        """
        try:
            import whisper          # noqa: F401 – just checking availability
            import sounddevice      # noqa: F401
        except ImportError as exc:
            logger.warning("VoiceListener disabled – missing dependency: %s", exc)
            return

        try:
            import whisper as _whisper
            logger.info("Loading Whisper model '%s'…", self._model_name)
            self._model = _whisper.load_model(self._model_name)
            logger.info("Whisper model ready.")
        except Exception as exc:
            logger.warning("VoiceListener disabled – Whisper load failed: %s", exc)
            return

        self.enabled = True
        self._stop_event.clear()

        self._capture_thread = threading.Thread(
            target=self._capture_worker,
            name="whaip-voice-capture",
            daemon=True,
        )
        self._capture_thread.start()

        self._bridge_task = asyncio.create_task(
            self._bridge_loop(), name="whaip-voice-bridge"
        )
        logger.info("VoiceListener started (mic → Whisper → queue).")

    async def teardown(self) -> None:
        """Stop the microphone thread and background tasks gracefully."""
        self._stop_event.set()

        if self._bridge_task and not self._bridge_task.done():
            self._bridge_task.cancel()
            try:
                await self._bridge_task
            except asyncio.CancelledError:
                pass

        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=3.0)

        logger.info("VoiceListener stopped.")

    # ── Capture thread (runs outside the event loop) ───────────────────────

    def _capture_worker(self) -> None:
        """
        Opens the system microphone via sounddevice and feeds audio blocks
        through a simple energy-based VAD.  Complete utterances (numpy arrays)
        are placed on _raw_queue for the async bridge to transcribe.
        """
        try:
            import sounddevice as sd
        except ImportError:
            logger.error("sounddevice import failed inside capture thread.")
            return

        audio_buf: list[np.ndarray] = []
        silence_count  = 0
        onset_count    = 0
        in_speech      = False

        def _sd_callback(
            indata: np.ndarray,
            frames: int,
            time_info,
            status,
        ) -> None:
            nonlocal silence_count, onset_count, in_speech

            if status:
                logger.debug("sounddevice status: %s", status)

            chunk = indata[:, 0].copy()   # mono float32
            rms   = float(np.sqrt(np.mean(chunk ** 2)))
            loud  = rms > RMS_THRESHOLD

            if loud:
                silence_count = 0
                onset_count  += 1
                if not in_speech and onset_count >= SPEECH_ONSET_BLOCKS:
                    in_speech = True
                    logger.debug("VAD: speech onset (rms=%.4f)", rms)
                if in_speech:
                    audio_buf.append(chunk)
            else:
                onset_count = 0
                if in_speech:
                    silence_count += 1
                    audio_buf.append(chunk)   # keep trailing silence for Whisper
                    if silence_count >= SILENCE_END_BLOCKS:
                        if len(audio_buf) >= MIN_SPEECH_BLOCKS:
                            utterance = np.concatenate(audio_buf)
                            self._raw_queue.put(utterance)
                            logger.debug(
                                "VAD: utterance queued (%.1f s)",
                                len(audio_buf) * BLOCK_SAMPLES / SAMPLE_RATE,
                            )
                        audio_buf.clear()
                        silence_count = 0
                        in_speech     = False

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=BLOCK_SAMPLES,
                callback=_sd_callback,
            ):
                logger.info("Microphone open – listening…")
                # Block this thread until teardown() sets the event
                while not self._stop_event.is_set():
                    self._stop_event.wait(timeout=0.1)
        except Exception as exc:
            logger.error("Microphone error: %s", exc)
            self.enabled = False

    # ── Async bridge (event-loop side) ─────────────────────────────────────

    async def _bridge_loop(self) -> None:
        """
        Polls _raw_queue for utterance arrays, transcribes them in the default
        executor (thread pool) so the event loop is never blocked, and pushes
        the text result to _text_queue.
        """
        loop = asyncio.get_running_loop()
        while True:
            try:
                # Non-blocking drain so we stay cooperative
                try:
                    audio_np = self._raw_queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.05)
                    continue

                # Transcription is CPU-bound – run in thread pool
                text: str = await loop.run_in_executor(
                    None, self._transcribe, audio_np
                )
                if text:
                    await self._text_queue.put(text)
                    logger.info("🎤 %s", text)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Bridge loop error: %s", exc)
                await asyncio.sleep(0.1)

    # ── Whisper inference ──────────────────────────────────────────────────

    def _transcribe(self, audio_np: np.ndarray) -> str:
        """
        Run Whisper on a mono float32 numpy array at 16 kHz.
        Returns stripped, lowercased text, or '' on failure.
        Runs synchronously inside a thread pool worker.
        """
        try:
            result = self._model.transcribe(
                audio_np,
                language=self._language,
                fp16=False,               # fp16 only safe on CUDA
                condition_on_previous_text=False,
            )
            text = result.get("text", "").strip().lower()

            # Discard known Whisper hallucinations
            _HALLUCINATIONS = {
                "", "you", "thank you", "thanks", "thank you.",
                "gracias", ".", "...", " ", "subtítulos realizados por la comunidad de amara.org",
                "suscríbete al canal", "www.", "sub"
            }
            if text in _HALLUCINATIONS:
                return ""

            # Reject if >30% of characters are non-Latin/non-Spanish
            # (Whisper hallucinates cyrillic/chinese on noise)
            import unicodedata
            non_latin = sum(
                1 for c in text
                if unicodedata.category(c).startswith('L')
                and ord(c) > 0x024F  # outside basic Latin + Latin extended
            )
            if len(text) > 0 and non_latin / len(text) > 0.15:
                logger.debug("Rejected hallucination (non-latin chars): %s", text[:60])
                return ""

            return text
        except Exception as exc:
            logger.error("Transcription error: %s", exc)
            return ""

    # ── Public API ─────────────────────────────────────────────────────────

    async def get_latest(self) -> Optional[str]:
        """
        Return the most recent transcription without blocking.
        Drains the entire queue and returns only the last item (most recent).
        Returns None if no transcription is waiting.
        """
        latest: Optional[str] = None
        while True:
            try:
                latest = self._text_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        return latest

    async def listen_once(self, timeout: float = 10.0) -> Optional[str]:
        """
        Wait up to `timeout` seconds for the next transcription.
        Returns None on timeout or if the listener is disabled.
        """
        if not self.enabled:
            return None
        try:
            return await asyncio.wait_for(self._text_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
