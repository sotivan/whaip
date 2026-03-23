"""
WHAIP – Supabase integration
Optional remote sync for memory, history, and preferences.
Disabled silently if supabase_url or supabase_key are empty.
"""

import logging
from .base import BaseIntegration

logger = logging.getLogger("whaip.integrations.supabase")

class SupabaseClient(BaseIntegration):

    def __init__(self, config: dict):
        super().__init__(config, required_keys=["supabase_url", "supabase_key"])
        self._client = None   # supabase.Client instance

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def setup(self):
        """Initialize Supabase client."""
        # TODO: if not self.enabled → return
        # TODO: from supabase import create_client
        # TODO: self._client = create_client(supabase_url, supabase_key)
        pass

    def teardown(self):
        """No persistent resources."""
        pass

    # ── Sync operations ────────────────────────────────────────────────────

    async def sync_turn(self, turn: dict):
        """
        Upsert a single agent turn to the `turns` table in Supabase.
        No-op if disabled.
        """
        # TODO: if not self.enabled → return
        # TODO: self._client.table("turns").upsert(turn).execute()
        pass

    async def sync_history(self, entry: dict):
        """
        Upsert a browser history entry to the `history` table.
        No-op if disabled.
        """
        # TODO: if not self.enabled → return
        # TODO: self._client.table("history").upsert(entry).execute()
        pass

    async def fetch_preferences(self, user_id: str) -> dict:
        """
        Fetch user preferences from Supabase.
        Returns empty dict if disabled or not found.
        """
        # TODO: if not self.enabled → return {}
        # TODO: res = self._client.table("preferences").select("*").eq("user_id", user_id).execute()
        # TODO: return {row["key"]: row["value"] for row in res.data}
        pass

    async def push_preferences(self, user_id: str, prefs: dict):
        """Push local preferences to Supabase."""
        # TODO: upsert rows into preferences table
        pass
