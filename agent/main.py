"""
WHAIP – Python agent entry point

Boots all subsystems and runs the main WHP loop.

Flow:
  Electron spawns this process on startup.
  We open a WebSocket server on ws://127.0.0.1:8765
  Electron connects and sends/receives WHP JSON messages.
  VoiceListener transcribes speech → we forward it to Electron.
  (Claude vision + action execution wired in next iterations)
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional

import yaml
import websockets
from websockets.server import WebSocketServerProtocol

from voice import VoiceListener

logger = logging.getLogger("whaip.main")

# ─── Config ────────────────────────────────────────────────────────────────

def load_config(path: str = "whaip.config.yaml") -> dict:
    """Load whaip.config.yaml. Missing file or keys return safe defaults."""
    cfg_path = Path(path)
    if not cfg_path.exists():
        # Try one level up (when running from agent/ subdir)
        cfg_path = Path(__file__).parent.parent / "whaip.config.yaml"

    if not cfg_path.exists():
        logger.warning("whaip.config.yaml not found – using empty config.")
        return {}

    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:
        logger.error("Failed to load config: %s", exc)
        return {}

# ─── Agent loop ────────────────────────────────────────────────────────────

class AgentLoop:
    """
    Orchestrates: voice → (vision + Claude → action) → ElevenLabs.
    WebSocket connections from Electron are registered here.
    """

    def __init__(self, config: dict):
        self.config  = config
        self.running = False
        self._clients: set[WebSocketServerProtocol] = set()

        # Subsystems — each disables itself silently if its key is missing
        self.voice = VoiceListener(config)

    async def setup(self) -> None:
        await self.voice.setup()

    async def teardown(self) -> None:
        await self.voice.teardown()

    # ── WebSocket client management ────────────────────────────────────────

    def register_client(self, ws: WebSocketServerProtocol) -> None:
        self._clients.add(ws)
        logger.info("Electron connected (%d clients)", len(self._clients))

    def unregister_client(self, ws: WebSocketServerProtocol) -> None:
        self._clients.discard(ws)
        logger.info("Electron disconnected (%d clients)", len(self._clients))

    async def broadcast(self, payload: dict) -> None:
        """Send a WHP JSON payload to all connected Electron windows."""
        if not self._clients:
            return
        message = json.dumps(payload, ensure_ascii=False)
        dead = set()
        for ws in self._clients:
            try:
                await ws.send(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def handle_incoming(self, message: str) -> None:
        """Handle a WHP message sent by Electron."""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("Bad JSON from Electron: %s", message[:120])
            return

        msg_type = data.get("type", "")
        logger.debug("← Electron: %s", msg_type)

        # Screenshot response (Electron sends this after we request it)
        if msg_type == "screenshot:response":
            self._pending_screenshot = data.get("data")

        # Electron acknowledged an action
        elif msg_type == "action:done":
            logger.info("Action done: %s", data.get("action"))

    # ── Main tick ─────────────────────────────────────────────────────────

    async def tick(self) -> None:
        """
        Single agent cycle.
        Currently: forward voice transcriptions to Electron for display.
        Claude vision + action execution will plug in here next.
        """
        if not self.voice.enabled:
            return

        text = await self.voice.get_latest()
        if not text:
            return

        logger.info("Voice → Electron: %s", text)
        await self.broadcast({
            "type": "transcript",
            "role": "user",
            "text": text,
        })

    async def run(self) -> None:
        """Main loop."""
        self.running = True
        interval = self.config.get("agent", {}).get("loop_interval_ms", 200) / 1000
        while self.running:
            try:
                await self.tick()
            except Exception as exc:
                logger.exception("Tick error: %s", exc)
            await asyncio.sleep(interval)

    def stop(self) -> None:
        self.running = False

# ─── WebSocket server ──────────────────────────────────────────────────────

async def ws_handler(
    websocket: WebSocketServerProtocol,
    agent: AgentLoop,
) -> None:
    """Handle one Electron WebSocket connection."""
    agent.register_client(websocket)
    try:
        async for message in websocket:
            await agent.handle_incoming(message)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        agent.unregister_client(websocket)


async def start_ws_server(config: dict, agent: AgentLoop) -> None:
    """Start the WHP WebSocket server and run until cancelled."""
    host = config.get("ws", {}).get("host", "127.0.0.1")
    port = config.get("ws", {}).get("port", 8765)

    handler = lambda ws, _path=None: ws_handler(ws, agent)

    async with websockets.serve(handler, host, port):
        logger.info("WHP WebSocket server listening on ws://%s:%d", host, port)
        await asyncio.Future()   # run forever

# ─── Entry point ───────────────────────────────────────────────────────────

async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)-20s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    config = load_config()
    agent  = AgentLoop(config)

    await agent.setup()

    try:
        await asyncio.gather(
            start_ws_server(config, agent),
            agent.run(),
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        agent.stop()
        await agent.teardown()
        logger.info("WHAIP agent stopped.")


if __name__ == "__main__":
    asyncio.run(main())
