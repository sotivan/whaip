"""
WHAIP – Claude API client

Agentic loop: Claude receives (screenshot + voice + history) and decides
the next action. It keeps going until action=done or max_steps reached.
Disabled silently if anthropic_api_key is empty.
"""

import json
import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger("whaip.claude")

WHP_ACTIONS = {"click", "type", "scroll", "navigate", "wait", "js", "done"}

SYSTEM_PROMPT = """You are WHAIP, an autonomous AI agent that controls a web browser.

You receive:
- A screenshot of the current browser state.
- The user's voice command (the goal to achieve).
- The history of actions already attempted this turn.

Your job: decide the NEXT action to get closer to the goal.
Keep acting until the goal is fully achieved, then return action=done.

Respond ONLY with a valid JSON object — no markdown, no extra text:
{
  "action": "click" | "type" | "scroll" | "navigate" | "wait" | "js" | "done",
  "x": <integer — for click>,
  "y": <integer — for click>,
  "text": "<for click: button label | for type: text to type | for navigate: URL>",
  "code": "<for js: complete JavaScript to run in the page>",
  "direction": "up" | "down",
  "reason": "<what you are doing and why — always present>"
}

Rules:
- Analyze the screenshot carefully before acting. Check if previous actions worked.
- If a click failed (element looks the same), switch to js immediately.
- If js failed, write better js — inspect selectors more carefully.
- Use setInput(el, value) to fill ANY text field (works on React/Vue/Angular).
- Use pressEnter(el) to submit a search or form.
- Common patterns:
    YouTube search:  const i=document.querySelector('input#search'); setInput(i,'QUERY'); pressEnter(i);
    Google search:   const i=document.querySelector('input[name="q"]'); setInput(i,'QUERY'); pressEnter(i);
    Accept cookies:  [...document.querySelectorAll('button')].find(b=>/aceptar|accept/i.test(b.innerText))?.click();
    Click by text:   [...document.querySelectorAll('button,a,[role="button"]')].find(e=>/TEXT/i.test(e.innerText))?.click();
- Return action=done ONLY when the goal is visibly achieved in the screenshot.
- Reply in the same language the user spoke.""".strip()


class ClaudeClient:

    def __init__(self, config: dict):
        self.config  = config
        self.enabled = bool(config.get("anthropic_api_key", "").strip())
        self._client = None

    def setup(self) -> None:
        if not self.enabled:
            logger.info("ClaudeClient disabled (no anthropic_api_key).")
            return
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.config["anthropic_api_key"])
            logger.info("ClaudeClient ready.")
        except ImportError:
            logger.warning("ClaudeClient disabled – anthropic package not installed.")
            self.enabled = False
        except Exception as exc:
            logger.warning("ClaudeClient disabled – %s", exc)
            self.enabled = False

    # ── Public API ─────────────────────────────────────────────────────────

    async def decide(
        self,
        voice_text: Optional[str],
        hand_pos: Optional[Tuple[float, float]],
        screenshot_b64: Optional[str],
        history: Optional[list] = None,   # list of previous {action, reason} dicts
        memory=None,
    ) -> dict:
        """
        Ask Claude for the next action given current state + history.
        Never raises — returns wait on any error.
        """
        if not self.enabled or not self._client:
            return {"action": "wait", "reason": "Claude no configurado."}

        try:
            content = self._build_content(voice_text, hand_pos, screenshot_b64, history or [])

            import asyncio
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.messages.create(
                    model="claude-opus-4-6",
                    max_tokens=512,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": content}],
                ),
            )

            raw = response.content[0].text
            return self._parse_response(raw)

        except Exception as exc:
            logger.error("Claude API error: %s", exc)
            return {"action": "wait", "reason": f"Error: {exc}"}

    # ── Internal ───────────────────────────────────────────────────────────

    def _build_content(
        self,
        voice_text: Optional[str],
        hand_pos: Optional[Tuple[float, float]],
        screenshot_b64: Optional[str],
        history: list,
    ) -> list:
        content = []

        if screenshot_b64:
            content.append({
                "type": "image",
                "source": {
                    "type":       "base64",
                    "media_type": "image/jpeg",
                    "data":       screenshot_b64,
                },
            })

        parts = []
        if voice_text:
            parts.append(f"OBJETIVO DEL USUARIO: {voice_text}")
        if hand_pos:
            parts.append(f"Dedo índice en: x={hand_pos[0]:.0f}, y={hand_pos[1]:.0f}")

        if history:
            parts.append("\nACCIONES YA INTENTADAS:")
            for i, h in enumerate(history, 1):
                parts.append(f"  {i}. {h.get('action')} — {h.get('reason','')}")
            parts.append("\nAnaliza el screenshot y decide la siguiente acción.")
        else:
            parts.append("\nPrimera acción. Analiza el screenshot y decide qué hacer.")

        content.append({"type": "text", "text": "\n".join(parts)})
        return content

    def _parse_response(self, raw: str) -> dict:
        text = raw.strip()
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    return {"action": "wait", "reason": "Respuesta no parseable."}
            else:
                return {"action": "wait", "reason": "Sin JSON en respuesta."}

        action = data.get("action", "wait")
        if action not in WHP_ACTIONS:
            data["action"] = "wait"

        if not data.get("reason"):
            data["reason"] = action

        logger.info("Claude → %s | %s", data["action"], data.get("reason", ""))
        return data
