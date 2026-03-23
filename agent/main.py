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
from intent import IntentClassifier
from tts    import TTSClient
from memory import UserMemory

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

        # pending screenshot / DOM responses from Electron
        self._screenshot_event  = asyncio.Event()
        self._pending_screenshot: Optional[str] = None
        self._dom_event         = asyncio.Event()
        self._pending_dom:       Optional[str] = None
        self._current_task: Optional[asyncio.Task] = None
        self._action_results: dict = {}   # action_id → result dict

        self.voice  = VoiceListener(config)
        self.claude = ClaudeClient(config)
        self.intent = IntentClassifier(config)
        self.memory = UserMemory()
        self.tts    = TTSClient(config, memory=self.memory)

        # When agent is waiting for a voice answer to a question
        self._waiting_for_answer = False

    async def setup(self) -> None:
        await self.voice.setup()
        self.claude.setup()
        self.intent.setup()

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

        elif msg_type == "mic:toggle":
            self.voice.set_active(data.get("active", True))

        elif msg_type == "page:context":
            self.intent.update_context(
                url=data.get("url", ""),
                title=data.get("title", ""),
            )

        elif msg_type == "dom:response":
            self._pending_dom = data.get("data")
            self._dom_event.set()

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

    # ── Wait for a specific action result ────────────────────────────────

    async def _wait_for_action_result(self, action_id: str, timeout: float = 12.0) -> Optional[dict]:
        """Wait until action_id appears in _action_results or timeout."""
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if action_id in self._action_results:
                return self._action_results[action_id]
            await asyncio.sleep(0.2)
        logger.debug("_wait_for_action_result: timeout for %s", action_id)
        return None

    # ── DOM snapshot request ───────────────────────────────────────────────

    async def request_dom_snapshot(self, timeout: float = 2.5) -> Optional[str]:
        """Ask Electron for a DOM snapshot; returns JSON string or None."""
        if not self._clients:
            return None
        self._pending_dom = None
        self._dom_event.clear()
        await self.broadcast({"type": "dom:request"})
        try:
            await asyncio.wait_for(self._dom_event.wait(), timeout=timeout)
            return self._pending_dom
        except asyncio.TimeoutError:
            logger.warning("DOM snapshot request timed out.")
            return None

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

    # ── Agent meta-commands (handle inline, don't cancel current task) ────

    _VOICE_MAP = {
        "adam":    "pNInz6obpgDQGcFmaJgB",
        "hombre":  "pNInz6obpgDQGcFmaJgB",
        "male":    "pNInz6obpgDQGcFmaJgB",
        "antoni":  "ErXwobaYiN019PkySvjV",
        "josh":    "TxGEqnHWrfWFTfGW9XjX",
        "rachel":  "21m00Tcm4TlvDq8ikWAM",
        "mujer":   "EXAVITQu4vr4xnSDxMaL",
        "female":  "EXAVITQu4vr4xnSDxMaL",
        "bella":   "EXAVITQu4vr4xnSDxMaL",
    }

    async def _handle_meta_command(self, intent: str) -> bool:
        """
        Handle agent-level commands without cancelling the current browser task.
        Returns True if the command was handled here (don't start a new task).
        """
        import re
        t = intent.lower()

        # ── Voice change ──────────────────────────────────────────────────
        if re.search(r"cambia|cambi|otra voz|voz de |change voice|voice", t):
            for name, vid in self._VOICE_MAP.items():
                if name in t:
                    self.tts.set_voice(vid)
                    await self.say(f"Cambiado a voz de {name.capitalize()}.")
                    await self.broadcast({"type": "transcript", "role": "assistant",
                                          "text": f"[voz → {name}]"})
                    return True
            # Generic "cambia la voz" without a name → pick the opposite gender
            current = self.memory.get("elevenlabs_voice_id") or ""
            if current in ("EXAVITQu4vr4xnSDxMaL", "21m00Tcm4TlvDq8ikWAM"):
                self.tts.set_voice("pNInz6obpgDQGcFmaJgB")
                await self.say("Cambiado a voz masculina.")
            else:
                self.tts.set_voice("EXAVITQu4vr4xnSDxMaL")
                await self.say("Cambiado a voz femenina.")
            return True

        # ── Stop / cancel current task ────────────────────────────────────
        if re.match(r"^(para|stop|cancela|detente|cancela todo)", t):
            if self._current_task and not self._current_task.done():
                self.tts.stop()
                self._current_task.cancel()
                try:
                    await self._current_task
                except asyncio.CancelledError:
                    pass
                await self.broadcast({"type": "status", "state": "idle"})
                await self.say("Cancelado.")
            return True

        return False

    # ── Voice conversation helpers ─────────────────────────────────────────

    async def say(self, text: str) -> None:
        """Speak text and show in sidebar."""
        logger.info("🔊 %s", text)
        await self.broadcast({"type": "transcript", "role": "assistant", "text": text})
        await self.tts.speak(text)

    async def ask_and_wait(self, question: str, timeout: float = 15.0) -> Optional[str]:
        """
        Speak a question, then wait for the user's voice answer.
        Returns the transcribed answer or None on timeout.
        """
        self._waiting_for_answer = True
        await self.say(question)
        await self.broadcast({"type": "status", "state": "listening"})

        # Drain any stale transcriptions first
        await self.voice.get_latest()

        try:
            answer = await asyncio.wait_for(
                self.voice.listen_once(timeout=timeout),
                timeout=timeout + 1,
            )
            return answer
        except asyncio.TimeoutError:
            return None
        finally:
            self._waiting_for_answer = False
            await self.broadcast({"type": "status", "state": "thinking"})

    # ── Agentic task loop ─────────────────────────────────────────────────

    async def run_task(self, goal: str) -> None:
        """
        Run a full agentic loop for a single user goal.
        Claude acts → sees result → acts again until done or max_steps.
        Supports ask/speak actions for conversational clarification.
        """
        MAX_STEPS  = 12
        STEP_DELAY = 1.2   # seconds between actions (let page settle)
        history    = []
        action_counter = 0
        last_action    = None

        # Inject user profile so Claude knows what it already knows
        profile = self.memory.get_profile_summary()

        await self.broadcast({"type": "status", "state": "thinking"})

        for step in range(MAX_STEPS):
            # DOM snapshot: always (cheap JS, text-only context for Claude)
            dom_snapshot = await self.request_dom_snapshot()

            # Screenshot: only after navigation or every 5 steps (expensive vision)
            _VISUAL_ACTIONS = {None, "navigate", "scroll"}
            need_screenshot = (last_action in _VISUAL_ACTIONS) or (step % 5 == 0)
            screenshot = await self.request_screenshot() if need_screenshot else None

            cmd = await self.claude.decide(
                voice_text=goal,
                hand_pos=None,
                screenshot_b64=screenshot,
                dom_snapshot=dom_snapshot,
                history=history,
                memory=profile,
            )

            action = cmd.get("action", "wait")
            reason = cmd.get("reason", "")

            # ── Conversational actions (no browser execution) ──────────────

            if action == "set_voice":
                voice_id = cmd.get("voice_id", "")
                if voice_id:
                    self.tts.set_voice(voice_id)
                confirm = cmd.get("text", "Voz cambiada.")
                await self.say(confirm)
                history.append({"action": "set_voice", "reason": reason, "result": "ok"})
                continue

            if action == "speak":
                text = cmd.get("text", reason)
                await self.say(text)
                history.append({"action": "speak", "reason": text, "result": "dicho"})
                continue

            if action == "ask":
                question = cmd.get("text", reason)
                answer = await self.ask_and_wait(question)
                if answer:
                    logger.info("User answered: %s", answer)
                    await self.broadcast({"type": "transcript", "role": "user", "text": answer})
                    # Store answer in memory if Claude tagged a memory_key
                    memory_key = cmd.get("memory_key")
                    if memory_key:
                        self.memory.set(memory_key, answer)
                        profile = self.memory.get_profile_summary()
                    history.append({
                        "action": "ask",
                        "reason": question,
                        "result": f"usuario respondió: {answer}",
                    })
                    # Re-state the goal enriched with the answer
                    goal = f"{goal} [{memory_key or 'info'}: {answer}]"
                else:
                    history.append({"action": "ask", "reason": question, "result": "sin respuesta"})
                continue

            # ── Loop detection: same action 3× in a row → force escape ────
            if len(history) >= 3:
                last3 = [h["action"] for h in history[-3:]]
                if len(set(last3)) == 1 and last3[0] in ("click", "js", "wait", "navigate"):
                    escape = (
                        f" [⚠️ BUCLE: llevas {len(last3)} pasos repitiendo '{last3[0]}' "
                        f"sin avanzar. Cambia COMPLETAMENTE de estrategia: "
                        f"usa navigate a una URL directa, o JS nuclear para quitar overlays, "
                        f"o declara done si el objetivo ya no es alcanzable.]"
                    )
                    if escape not in goal:
                        goal = goal + escape
                        logger.warning("Loop detected (%s ×3) — injecting escape hint", last3[0])

            # ── Browser actions ────────────────────────────────────────────

            action_counter += 1
            action_id = f"a{action_counter}"
            cmd["_id"] = action_id

            await self.broadcast({"type": "action", **cmd})

            # For navigate: wait for did-finish-load result (up to 12s), then short settle
            # For everything else: fixed step delay
            if action == "navigate":
                await self._wait_for_action_result(action_id, timeout=12.0)
                await asyncio.sleep(0.5)   # brief settle after page load
            else:
                await asyncio.sleep(STEP_DELAY)

            result = self._action_results.pop(action_id, None)
            result_str = ""
            if result:
                if result.get("ok"):
                    detail = result.get("result", "")
                    url    = result.get("url", "")
                    result_str = f"✓ {detail} | URL: {url}" if detail else f"✓ ok | URL: {url}"
                else:
                    result_str = f"✗ ERROR: {result.get('error','?')} | URL: {result.get('url','')}"

            last_action = action
            history.append({
                "action": action,
                "reason": reason,
                "result": result_str or "sin feedback (click/navigate/type)",
            })

            if action == "done":
                speak_text = cmd.get("text", "")
                if speak_text:
                    await self.say(speak_text)
                logger.info("Task complete after %d steps: %s", step + 1, goal)
                await self.broadcast({"type": "status", "state": "idle"})
                return

            if action == "wait":
                continue

        logger.warning("Task hit max_steps (%d): %s", MAX_STEPS, goal)
        await self.say("He llegado al límite de pasos. Intenta de nuevo.")
        await self.broadcast({
            "type": "action",
            "action": "done",
            "reason": "Límite de pasos alcanzado.",
        })
        await self.broadcast({"type": "status", "state": "idle"})

    # ── Main tick ─────────────────────────────────────────────────────────

    async def tick(self) -> None:
        raw = await self.voice.get_latest()
        if not raw:
            return

        # Don't interrupt while waiting for a conversational answer
        if self._waiting_for_answer:
            return

        # ── Intent classification: is this a real command? ──
        intent = await self.intent.classify(raw)
        if not intent:
            logger.debug("Discarded (not a command): %s", raw[:60])
            return

        await self.broadcast({"type": "transcript", "role": "user", "text": intent})

        # ── Agent meta-commands (voice, stop…) — run inline, keep current task ──
        if await self._handle_meta_command(intent):
            return

        # ── Browser task — cancel any running task, start fresh ────────────
        if self._current_task and not self._current_task.done():
            self.tts.stop()   # kill audio immediately so new command can speak
            self._current_task.cancel()
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass
            await self.broadcast({"type": "status", "state": "idle"})

        logger.info("Command: %s", intent)
        self._current_task = asyncio.create_task(self.run_task(intent))

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
