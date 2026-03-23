"""
WHAIP – Python agent entry point
Boots all subsystems and runs the main WHP loop.
"""

import asyncio
import logging
import yaml
from pathlib import Path

from voice   import VoiceListener
from vision  import VisionTracker
from claude  import ClaudeClient
from executor import ActionExecutor
from memory  import Memory
from integrations.elevenlabs import ElevenLabsClient
from integrations.supabase   import SupabaseClient
from integrations.google     import GoogleAuthClient

logger = logging.getLogger("whaip.main")

# ─── Config ────────────────────────────────────────────────────────────────

def load_config(path: str = "whaip.config.yaml") -> dict:
    """Load and return the YAML config. Missing keys return empty strings."""
    # TODO: read YAML file, return dict with defaults for missing keys
    pass

# ─── WebSocket server (WHP bridge with Electron) ───────────────────────────

async def ws_handler(websocket, config: dict, agent: "AgentLoop"):
    """Handle a single Electron WS connection."""
    # TODO: register websocket on agent, read messages in loop, dispatch to agent
    pass

async def start_ws_server(config: dict, agent: "AgentLoop"):
    """Start the WebSocket server on the configured host:port."""
    # TODO: import websockets, serve ws_handler bound to config and agent
    pass

# ─── Agent loop ────────────────────────────────────────────────────────────

class AgentLoop:
    """Orchestrates voice → vision → Claude → action → ElevenLabs cycle."""

    def __init__(self, config: dict):
        self.config   = config
        self.ws       = None      # active Electron websocket connection
        self.running  = False

        self.voice    = VoiceListener(config)
        self.vision   = VisionTracker(config)
        self.claude   = ClaudeClient(config)
        self.executor = ActionExecutor(config)
        self.memory   = Memory(config)
        self.tts      = ElevenLabsClient(config)
        self.supabase = SupabaseClient(config)
        self.google   = GoogleAuthClient(config)

    async def send_to_electron(self, payload: dict):
        """Send a WHP JSON payload to the connected Electron window."""
        # TODO: serialize payload and send via self.ws if connected
        pass

    async def tick(self):
        """Single iteration of the main agent loop."""
        # 1. Get latest voice transcription (non-blocking)
        # TODO: voice_text = await self.voice.get_latest()

        # 2. Get current hand/finger position from webcam
        # TODO: hand_pos = await self.vision.get_finger_position()

        # 3. Request screenshot from Electron
        # TODO: screenshot_b64 = await self.request_screenshot()

        # 4. Ask Claude for next action
        # TODO: cmd = await self.claude.decide(voice_text, hand_pos, screenshot_b64, self.memory)

        # 5. Send action to Electron for execution
        # TODO: await self.send_to_electron(cmd)

        # 6. Speak response via ElevenLabs
        # TODO: await self.tts.speak(cmd.get("reason", ""))

        # 7. Persist to memory
        # TODO: await self.memory.save_turn(voice_text, cmd)

        pass

    async def request_screenshot(self) -> str:
        """Ask Electron for a screenshot; returns base64 JPEG string."""
        # TODO: send 'screenshot:request' WHP message, await 'screenshot:response'
        pass

    async def run(self):
        """Main loop. Calls tick() on the configured interval."""
        self.running = True
        interval = self.config.get("agent", {}).get("loop_interval_ms", 500) / 1000
        while self.running:
            try:
                await self.tick()
            except Exception as e:
                logger.exception("Tick error: %s", e)
            await asyncio.sleep(interval)

    def stop(self):
        self.running = False

# ─── Entry point ───────────────────────────────────────────────────────────

async def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    config = load_config()
    agent  = AgentLoop(config)

    await asyncio.gather(
        start_ws_server(config, agent),
        agent.run(),
    )

if __name__ == "__main__":
    asyncio.run(main())
