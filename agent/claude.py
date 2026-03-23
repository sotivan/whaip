"""
WHAIP – Claude API client
Sends multimodal context (screenshot + voice + hand position) to Claude
and parses the WHP action JSON response.
Disabled silently if anthropic_api_key is empty.
"""

import logging
from typing import Optional, Tuple

logger = logging.getLogger("whaip.claude")

# WHP response schema (reference)
WHP_ACTIONS = {"click", "type", "scroll", "navigate", "wait", "done"}

SYSTEM_PROMPT = """
You are WHAIP, an AI agent that controls a web browser on behalf of the user.
You receive:
  - A screenshot of the current browser viewport (base64 JPEG).
  - The user's last voice command (may be empty).
  - The normalized (x, y) position of their index finger on the webcam (may be null).

Always respond with a single valid JSON object and nothing else:
{
  "action": "click" | "type" | "scroll" | "navigate" | "wait" | "done",
  "x": <integer pixel x, only for click>,
  "y": <integer pixel y, only for click>,
  "text": "<string, for type or navigate>",
  "direction": "up" | "down"  (only for scroll),
  "reason": "<always present, brief explanation>"
}
""".strip()

class ClaudeClient:
    """Calls the Claude API and parses WHP action responses."""

    def __init__(self, config: dict):
        self.config  = config
        self.enabled = bool(config.get("anthropic_api_key", "").strip())
        self._client = None   # anthropic.Anthropic instance

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def setup(self):
        """Initialize the Anthropic client. No-op if disabled."""
        # TODO: if not self.enabled → return
        # TODO: import anthropic; self._client = anthropic.Anthropic(api_key=...)
        pass

    # ── Public API ─────────────────────────────────────────────────────────

    async def decide(
        self,
        voice_text: Optional[str],
        hand_pos: Optional[Tuple[float, float]],
        screenshot_b64: Optional[str],
        memory,             # Memory instance for context injection
    ) -> dict:
        """
        Build a multimodal Claude message and return the parsed WHP action dict.
        Returns a 'wait' action with a reason if Claude is disabled or errors.
        """
        # TODO: if not self.enabled → return {"action": "wait", "reason": "Claude disabled"}
        # TODO: build messages list:
        #   - user message with image_url block (screenshot_b64)
        #   - text block with voice_text and hand_pos
        #   - inject relevant memory context
        # TODO: call self._client.messages.create(model="claude-opus-4-6", ...)
        # TODO: parse JSON from response.content[0].text
        # TODO: validate action field is in WHP_ACTIONS
        # TODO: return parsed dict; on parse error → {"action": "wait", "reason": "parse error"}
        pass

    def _build_user_message(
        self,
        voice_text: Optional[str],
        hand_pos: Optional[Tuple[float, float]],
        screenshot_b64: Optional[str],
        memory_context: str,
    ) -> list:
        """Build the Claude messages list for one decision turn."""
        # TODO: construct content blocks: image (if screenshot), then text summary
        pass

    def _parse_response(self, raw: str) -> dict:
        """Parse and validate a Claude JSON response string into a WHP dict."""
        # TODO: json.loads(raw), validate required fields, return dict
        pass
