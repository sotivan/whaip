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

from voice      import VoiceListener
from claude     import ClaudeClient
from intent     import IntentClassifier
from tts        import TTSClient
from memory     import UserMemory
from onboarding import OnboardingFlow

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

        # pending screenshot / DOM / geo responses from Electron
        self._screenshot_event  = asyncio.Event()
        self._pending_screenshot: Optional[str] = None
        self._dom_event         = asyncio.Event()
        self._pending_dom:       Optional[str] = None
        self._geo_event         = asyncio.Event()
        self._pending_geo:       Optional[dict] = None
        self._current_task: Optional[asyncio.Task] = None
        self._action_results: dict = {}   # action_id → result dict
        self._onboarding_done   = False

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

    async def _run_onboarding(self) -> None:
        self._onboarding_done = True
        self.voice.set_active(False)
        try:
            flow = OnboardingFlow(self)
            await flow.run()
        except Exception as exc:
            logger.exception("Onboarding error: %s", exc)
        finally:
            self.voice.set_active(False)  # keep mic off — user presses button to start

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

        elif msg_type == "script:result":
            script_id = data.get("script_id")
            if script_id:
                self._action_results[script_id] = data
                if data.get("ok"):
                    logger.info("Script [%s]: ✓ %s | %s", script_id, data.get("result", ""), data.get("url", ""))
                else:
                    logger.warning("Script [%s]: ✗ step %s (%s): %s",
                                   script_id, data.get("failed_step"), data.get("failed_desc"), data.get("error"))

        elif msg_type == "script:speak":
            text = data.get("text", "")
            if text:
                asyncio.create_task(self.say(text))

        elif msg_type == "geo:response":
            self._pending_geo = data
            self._geo_event.set()

        elif msg_type == "onboarding:answers":
            # UI form submitted — save all answers at once
            answers = data.get("answers", {})
            for key, value in answers.items():
                if value and str(value).strip():
                    self.memory.set(key, str(value).strip())
            logger.info("Onboarding form answers saved: %s", list(answers.keys()))

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

    # ── Geolocation request ────────────────────────────────────────────────

    async def request_geolocation(self, timeout: float = 8.0) -> Optional[dict]:
        """Ask browser for current GPS location. Returns {lat, lng} or None."""
        if not self._clients:
            return None
        self._pending_geo = None
        self._geo_event.clear()
        await self.broadcast({"type": "geo:request"})
        try:
            await asyncio.wait_for(self._geo_event.wait(), timeout=timeout)
            return self._pending_geo
        except asyncio.TimeoutError:
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
        Temporarily enables the mic even if it was off (e.g. during onboarding).
        Returns the transcribed answer or None on timeout.
        """
        self._waiting_for_answer = True
        self.voice.set_active(True)    # always enable mic for answering
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
            self.voice.set_active(False)   # back to off until user re-activates
            await self.broadcast({"type": "status", "state": "thinking"})

    # ── Agentic task loop ─────────────────────────────────────────────────

    async def run_task(self, goal: str) -> None:
        """
        Agentic loop: Claude plans → browser executes → re-plan if needed.

        Architecture:
          - Claude returns either a `script` (multi-step plan) or a single action.
          - Scripts run entirely in the browser without API round-trips between steps.
          - On script failure, Claude re-plans with the failure context.
          - Max MAX_ROUNDS planning calls per task (not individual steps).
        """
        MAX_ROUNDS = 5       # max Claude calls per task
        profile    = self.memory.get_profile_summary()
        history    : list    = []
        round_n    = 0
        _task_goal = goal    # keep original for recording

        # ── Location context for delivery tasks ───────────────────────────
        _DELIVERY_KEYWORDS = ("pide", "pedido", "pedir", "order", "deliver", "pizza",
                               "comida", "glovo", "just eat", "envío", "enviar")
        if any(k in goal.lower() for k in _DELIVERY_KEYWORDS):
            geo = await self.request_geolocation(timeout=5.0)
            if geo and geo.get("lat"):
                dist = self.memory.distance_from_home_km(geo["lat"], geo["lng"])
                if dist is not None and dist > 1.5:
                    profile += (f"\n\n⚠️ El usuario NO está en casa ahora mismo "
                                f"(a {dist:.1f} km de su dirección habitual). "
                                f"Pregunta a qué dirección quiere el pedido antes de proceder.")
                elif dist is not None:
                    profile += f"\n\nEl usuario está cerca de su domicilio habitual ({dist:.1f} km)."

        await self.broadcast({"type": "status", "state": "thinking"})

        for round_n in range(MAX_ROUNDS):

            dom_snapshot = await self.request_dom_snapshot()
            screenshot   = await self.request_screenshot()   # always: Claude needs to see to plan

            cmd    = await self.claude.decide(
                voice_text   = goal,
                hand_pos     = None,
                screenshot_b64 = screenshot,
                dom_snapshot = dom_snapshot,
                history      = history,
                memory       = profile,
            )
            action = cmd.get("action", "wait")
            reason = cmd.get("reason", "")

            # ── Conversational / meta ──────────────────────────────────────

            if action == "done":
                if cmd.get("text"):
                    await self.say(cmd["text"])
                logger.info("Task done after %d rounds: %s", round_n + 1, goal)
                self.memory.record_task(_task_goal, success=True)
                await self.broadcast({"type": "status", "state": "idle"})
                return

            if action == "speak":
                await self.say(cmd.get("text", reason))
                history.append({"action": "speak", "reason": reason, "result": "dicho"})
                continue

            if action == "ask":
                question = cmd.get("text", reason)
                answer   = await self.ask_and_wait(question)
                key      = cmd.get("memory_key")
                if answer:
                    await self.broadcast({"type": "transcript", "role": "user", "text": answer})
                    if key:
                        self.memory.set(key, answer)
                        profile = self.memory.get_profile_summary()
                    goal = f"{goal} [{key or 'info'}: {answer}]"
                history.append({"action": "ask", "reason": question,
                                 "result": f"answered: {answer or 'no answer'}"})
                continue

            if action == "set_voice":
                if cmd.get("voice_id"):
                    self.tts.set_voice(cmd["voice_id"])
                await self.say(cmd.get("text", "Voz cambiada."))
                history.append({"action": "set_voice", "reason": reason, "result": "ok"})
                continue

            if action == "wait":
                await asyncio.sleep(1.5)
                history.append({"action": "wait", "reason": reason, "result": "waited"})
                continue

            # ── Browser actions (script or single) ────────────────────────

            action_id  = f"r{round_n+1}"
            cmd["_id"] = action_id
            await self.broadcast({"type": "action", **cmd})

            if action == "script":
                result = await self._wait_for_action_result(action_id, timeout=90.0)
            elif action == "navigate":
                result = await self._wait_for_action_result(action_id, timeout=12.0)
                await asyncio.sleep(0.4)
                result = self._action_results.pop(action_id, result)
            else:
                await asyncio.sleep(1.2)
                result = self._action_results.pop(action_id, None)

            self._action_results.pop(action_id, None)  # cleanup

            if result:
                if result.get("ok"):
                    result_str = f"✓ {result.get('result','ok')} | URL: {result.get('url','')}"
                else:
                    result_str = (f"✗ step {result.get('failed_step','?')} "
                                  f"({result.get('failed_desc','?')}): {result.get('error','?')} "
                                  f"| URL: {result.get('url','')}")
            else:
                result_str = "no result / timeout"

            history.append({"action": action, "reason": reason, "result": result_str})
            logger.info("Round %d [%s]: %s", round_n + 1, action, result_str[:120])

        logger.warning("Task hit max_rounds (%d): %s", MAX_ROUNDS, goal)
        await self.say("No pude completar la tarea. Intenta de nuevo con más detalle.")
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
        self.voice.set_active(False)   # mic OFF until user presses the button
        interval = self.config.get("agent", {}).get("loop_interval_ms", 200) / 1000

        # Wait for first Electron connection, then start onboarding if needed
        while self.running and not self._clients:
            await asyncio.sleep(0.2)
        if self.running and not self.memory.is_onboarding_done() and not self._onboarding_done:
            self._onboarding_done = True
            asyncio.create_task(self._run_onboarding())

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
