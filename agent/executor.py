"""
WHAIP – Action executor
Validates and logs WHP action commands before they are forwarded to Electron.
(Actual DOM execution happens in browser.js on the Electron side.)
"""

import logging
from typing import Callable, Awaitable

logger = logging.getLogger("whaip.executor")

class ActionExecutor:
    """
    Validates WHP action dicts, applies pre/post hooks, and dispatches them
    to the registered sender (the AgentLoop.send_to_electron coroutine).
    """

    def __init__(self, config: dict):
        self.config = config
        self._sender: Callable[[dict], Awaitable[None]] = None

    # ── Setup ──────────────────────────────────────────────────────────────

    def set_sender(self, sender: Callable[[dict], Awaitable[None]]):
        """Register the coroutine used to forward actions to Electron."""
        # TODO: self._sender = sender
        pass

    # ── Validation ─────────────────────────────────────────────────────────

    def validate(self, cmd: dict) -> bool:
        """
        Return True if cmd is a structurally valid WHP action dict.
        Logs a warning and returns False on any violation.
        """
        # TODO: check 'action' key present and in WHP_ACTIONS
        # TODO: for 'click': x and y must be non-negative integers
        # TODO: for 'type'/'navigate': text must be a non-empty string
        # TODO: for 'scroll': direction must be 'up' or 'down'
        # TODO: 'reason' must always be a non-empty string
        pass

    # ── Execution ──────────────────────────────────────────────────────────

    async def execute(self, cmd: dict):
        """
        Validate and forward a WHP command to Electron.
        Skips execution if validation fails.
        """
        # TODO: if not self.validate(cmd) → return
        # TODO: log action and reason
        # TODO: await self._sender(cmd)
        pass

    # ── Hooks (future extension points) ───────────────────────────────────

    async def _pre_execute(self, cmd: dict):
        """Called before every action. Override for telemetry / guardrails."""
        pass

    async def _post_execute(self, cmd: dict):
        """Called after every action. Override for logging / Supabase sync."""
        pass
