"""
WHAIP – Python agent entry point

Flow:
  Electron spawns this process.
  We open a WebSocket server on ws://127.0.0.1:8765.
  Electron connects → sends screenshots + receives WHP actions.

  Loop:
    1. VoiceListener transcribes speech
    2. Request screenshot from Electron
    3. Send (voice + screenshot) to Claude
    4. Broadcast WHP action back to Electron for execution
    5. Speak response via ElevenLabs (if configured)
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

from voice  import VoiceListener
from claude import ClaudeClient

logger = logging.getLogger("whaip.main")

# ─── Config ────────────────────────────────────────────────────────────────

def load_config(path: str = "whaip.config.yaml") -> dict:
    cfg_path = Path(path)
    if not cfg_path.exists():
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

    def __init__(self, config: dict):
        self.config  = config
        self.running = False
        self._clients: set[WebSocketServerProtocol] = set()

        # pending screenshot response from Electron
        self._screenshot_event  = asyncio.Event()
        self._pending_screenshot: Optional[str] = None
        self._current_task: Optional[asyncio.Task] = None
        self._action_results: dict = {}   # action_id → result dict

        self.voice  = VoiceListener(config)
        self.claude = ClaudeClient(config)

    async def setup(self) -> None:
        await self.voice.setup()
        self.claude.setup()

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
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return

        msg_type = data.get("type", "")

        if msg_type == "screenshot:response":
            self._pending_screenshot = data.get("data")
            self._screenshot_event.set()

        elif msg_type == "action:result":
            action_id = data.get("action_id")
            if action_id:
                self._action_results[action_id] = data
                logger.info(
                    "Action result [%s]: ok=%s %s",
                    action_id,
                    data.get("ok"),
                    data.get("error", data.get("result", "")),
                )

    # ── Screenshot request ─────────────────────────────────────────────────

    async def request_screenshot(self, timeout: float = 3.0) -> Optional[str]:
        """Ask Electron for a screenshot; returns base64 JPEG or None."""
        if not self._clients:
            return None
        self._pending_screenshot = None
        self._screenshot_event.clear()
        await self.broadcast({"type": "screenshot:request"})
        try:
            await asyncio.wait_for(self._screenshot_event.wait(), timeout=timeout)
            return self._pending_screenshot
        except asyncio.TimeoutError:
            logger.warning("Screenshot request timed out.")
            return None

    # ── Agentic task loop ─────────────────────────────────────────────────

    async def run_task(self, goal: str) -> None:
        """
        Run a full agentic loop for a single user goal.
        Claude acts → sees result → acts again until done or max_steps.
        """
        MAX_STEPS  = 8
        STEP_DELAY = 1.5   # seconds between actions (let page settle)
        history    = []
        action_counter = 0

        await self.broadcast({"type": "status", "state": "thinking"})

        for step in range(MAX_STEPS):
            screenshot = await self.request_screenshot()

            cmd = await self.claude.decide(
                voice_text=goal,
                hand_pos=None,
                screenshot_b64=screenshot,
                history=history,
            )

            action = cmd.get("action", "wait")
            reason = cmd.get("reason", "")

            # Tag action with ID so we can match result
            action_counter += 1
            action_id = f"a{action_counter}"
            cmd["_id"] = action_id

            # Show in sidebar
            await self.broadcast({"type": "action", **cmd})

            # Wait for execution + page reaction
            await asyncio.sleep(STEP_DELAY)

            # Collect result feedback if available
            result = self._action_results.pop(action_id, None)
            result_str = ""
            if result:
                if result.get("ok"):
                    result_str = f"✓ ejecutado ok. URL actual: {result.get('url','')}"
                else:
                    result_str = f"✗ ERROR: {result.get('error','unknown error')}"

            history.append({
                "action": action,
                "reason": reason,
                "result": result_str or "sin feedback (click/navigate/type)",
            })

            if action == "done":
                logger.info("Task complete after %d steps: %s", step + 1, goal)
                await self.broadcast({"type": "status", "state": "idle"})
                return

            if action == "wait":
                continue

        logger.warning("Task hit max_steps (%d): %s", MAX_STEPS, goal)
        await self.broadcast({
            "type": "action",
            "action": "done",
            "reason": "He llegado al límite de pasos. Intenta de nuevo.",
        })
        await self.broadcast({"type": "status", "state": "idle"})

    # ── Main tick ─────────────────────────────────────────────────────────

    async def tick(self) -> None:
        text = await self.voice.get_latest()
        if not text:
            return

        # New voice command → cancel whatever is running
        if self._current_task and not self._current_task.done():
            logger.info("New command received, cancelling current task.")
            self._current_task.cancel()
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass
            await self.broadcast({"type": "status", "state": "idle"})

        logger.info("Voice goal: %s", text)
        await self.broadcast({"type": "transcript", "role": "user", "text": text})

        # Run task in background so tick() returns immediately
        self._current_task = asyncio.create_task(self.run_task(text))

    async def run(self) -> None:
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

async def ws_handler(websocket: WebSocketServerProtocol, agent: AgentLoop) -> None:
    agent.register_client(websocket)
    try:
        async for message in websocket:
            await agent.handle_incoming(message)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        agent.unregister_client(websocket)


async def start_ws_server(config: dict, agent: AgentLoop) -> None:
    host = config.get("ws", {}).get("host", "127.0.0.1")
    port = config.get("ws", {}).get("port", 8765)

    handler = lambda ws, _path=None: ws_handler(ws, agent)

    async with websockets.serve(handler, host, port):
        logger.info("WHP server on ws://%s:%d", host, port)
        await asyncio.Future()

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
