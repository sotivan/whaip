"""
WHAIP – Claude API client

Sends multimodal context (screenshot + voice + hand position) to Claude
and returns a WHP action JSON.
Disabled silently if anthropic_api_key is empty.
"""

import json
import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger("whaip.claude")

WHP_ACTIONS = {"click", "type", "scroll", "navigate", "wait", "done", "js"}

SYSTEM_PROMPT = """You are WHAIP, an AI agent that controls a web browser for the user.

You receive:
- A screenshot of the current browser viewport.
- The user's voice command.
- The (x, y) position of their index finger on screen (if available).

Your job: decide the single best next browser action.

Respond ONLY with a valid JSON object, no markdown, no explanation:
{
  "action": "click" | "type" | "scroll" | "navigate" | "wait" | "js" | "done",
  "x": <integer pixel x — for click>,
  "y": <integer pixel y — for click>,
  "text": "<for click: visible label of button | for type: text to type | for navigate: URL>",
  "code": "<for js: complete JavaScript to execute in the page>",
  "direction": "up" | "down",
  "reason": "<brief explanation in the user's language, always present>"
}

Rules:
- For navigation: action=navigate, text=full URL.
- For clicking a button/link: action=click, x/y=coordinates, text=visible label.
- For typing: action=type, text=what to type.
- Use action=js when standard actions are unreliable or insufficient.
  Two helpers are available in your JS code: setInput(el, value) and pressEnter(el).
  Always use setInput() to fill text fields — it works on React/Vue/Angular sites.
  Examples:
    • YouTube search: const inp = document.querySelector('input#search'); setInput(inp, 'duki'); pressEnter(inp);
    • Accept cookies: document.querySelector('button[aria-label*="cept"]')?.click() || [...document.querySelectorAll('button')].find(b=>b.innerText.includes('Aceptar'))?.click()
    • Google search: const q = document.querySelector('input[name="q"]'); setInput(q, 'duki'); pressEnter(q);
    • Click by text: [...document.querySelectorAll('button,a')].find(e=>e.innerText.includes('TEXT'))?.click()
- ALWAYS use js when a click has already failed once. Do not repeat the same click action.
- NEVER include markdown fences or any text outside the JSON object.
- Reply in the same language the user speaks.""".strip()


class ClaudeClient:
    """Calls the Claude API and parses WHP action responses."""

    def __init__(self, config: dict):
        self.config  = config
        self.enabled = bool(config.get("anthropic_api_key", "").strip())
        self._client = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def setup(self) -> None:
        if not self.enabled:
            logger.info("ClaudeClient disabled (no anthropic_api_key).")
            return
        try:
            import anthropic
            self._client = anthropic.Anthropic(
                api_key=self.config["anthropic_api_key"]
            )
            logger.info("ClaudeClient ready.")
        except ImportError:
            logger.warning("ClaudeClient disabled – anthropic package not installed.")
            self.enabled = False
        except Exception as exc:
            logger.warning("ClaudeClient disabled – init error: %s", exc)
            self.enabled = False

    # ── Public API ─────────────────────────────────────────────────────────

    async def decide(
        self,
        voice_text: Optional[str],
        hand_pos: Optional[Tuple[float, float]],
        screenshot_b64: Optional[str],
        memory=None,
    ) -> dict:
        """
        Ask Claude what to do next given the current context.
        Returns a WHP action dict. Never raises — returns wait on any error.
        """
        if not self.enabled or not self._client:
            return {"action": "wait", "reason": "Claude no configurado."}

        if not voice_text and not screenshot_b64:
            return {"action": "wait", "reason": "Sin input."}

        try:
            memory_context = ""
            if memory:
                try:
                    memory_context = await memory.get_context()
                except Exception:
                    pass

            content = self._build_content(voice_text, hand_pos, screenshot_b64, memory_context)

            import asyncio
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.messages.create(
                    model="claude-opus-4-6",
                    max_tokens=256,
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
        memory_context: str,
    ) -> list:
        content = []

        # Screenshot (vision)
        if screenshot_b64:
            content.append({
                "type": "image",
                "source": {
                    "type":       "base64",
                    "media_type": "image/jpeg",
                    "data":       screenshot_b64,
                },
            })

        # Text context block
        parts = []
        if voice_text:
            parts.append(f"Comando de voz: {voice_text}")
        if hand_pos:
            parts.append(f"Dedo índice en pantalla: x={hand_pos[0]:.0f}, y={hand_pos[1]:.0f}")
        if memory_context:
            parts.append(f"Contexto previo:\n{memory_context}")
        if not parts:
            parts.append("Sin comando de voz. Analiza la pantalla y espera.")

        content.append({"type": "text", "text": "\n".join(parts)})
        return content

    def _parse_response(self, raw: str) -> dict:
        """Extract and validate the WHP JSON from Claude's response."""
        text = raw.strip()

        # Strip accidental markdown fences
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try extracting a JSON object from surrounding prose
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    logger.error("Unparseable Claude response: %s", text[:200])
                    return {"action": "wait", "reason": "Respuesta no parseable."}
            else:
                logger.error("No JSON in Claude response: %s", text[:200])
                return {"action": "wait", "reason": "Sin JSON en respuesta."}

        # Validate action
        action = data.get("action", "wait")
        if action not in WHP_ACTIONS:
            logger.warning("Unknown action '%s', defaulting to wait.", action)
            data["action"] = "wait"

        # Ensure reason is always present
        if not data.get("reason"):
            data["reason"] = action

        logger.info("Claude → %s | %s", data["action"], data.get("reason", ""))
        return data
