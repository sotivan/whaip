"""
WHAIP – Local memory module
Stores conversation turns, visited URLs, and user preferences in SQLite.
Optionally syncs to Supabase if credentials are configured.
"""

import logging
from typing import Optional

logger = logging.getLogger("whaip.memory")

DB_PATH = "~/.whaip/memory.db"

class Memory:
    """
    SQLite-backed short and long-term memory for the agent.
    Schema: turns(id, timestamp, voice_text, action_json, url)
            preferences(key, value)
            history(url, title, visited_at)
    """

    def __init__(self, config: dict):
        self.config   = config
        self._db      = None   # peewee SqliteDatabase instance
        self._supabase = None  # optional SupabaseClient for sync

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def setup(self):
        """Create DB file, run migrations, connect Supabase if configured."""
        # TODO: import peewee, expand DB_PATH with os.path.expanduser
        # TODO: create parent dir if needed
        # TODO: connect SqliteDatabase
        # TODO: create_tables([Turn, Preference, History])
        pass

    def teardown(self):
        """Close the database connection."""
        # TODO: self._db.close()
        pass

    # ── Turn memory ────────────────────────────────────────────────────────

    async def save_turn(self, voice_text: Optional[str], cmd: dict):
        """Persist one agent loop turn to the turns table."""
        # TODO: insert Turn(voice_text=voice_text, action_json=json.dumps(cmd), ...)
        # TODO: if supabase enabled → async sync
        pass

    async def get_recent_turns(self, n: int = 10) -> list[dict]:
        """Return the last n turns as a list of dicts for context injection."""
        # TODO: query Turn ORDER BY timestamp DESC LIMIT n, serialize to dicts
        pass

    # ── Preferences ────────────────────────────────────────────────────────

    def set_preference(self, key: str, value: str):
        """Upsert a user preference."""
        # TODO: Preference.insert_or_replace(key=key, value=value).execute()
        pass

    def get_preference(self, key: str, default: str = "") -> str:
        """Read a user preference by key."""
        # TODO: query Preference where key == key, return value or default
        pass

    # ── Browser history ────────────────────────────────────────────────────

    async def record_visit(self, url: str, title: str):
        """Add a URL visit to the history table."""
        # TODO: insert History(url=url, title=title, visited_at=datetime.utcnow())
        pass

    async def search_history(self, query: str) -> list[dict]:
        """Full-text search over visited URLs and titles."""
        # TODO: SELECT * FROM history WHERE url LIKE %query% OR title LIKE %query%
        pass

    # ── Context for Claude ─────────────────────────────────────────────────

    async def build_context_string(self) -> str:
        """
        Return a compact text summary of recent turns and preferences
        suitable for injection into the Claude system prompt.
        """
        # TODO: fetch recent turns + all preferences, format as readable text
        pass

# ─── Peewee models (defined here, connected in Memory.setup) ──────────────

# TODO: define Turn, Preference, History as peewee.Model subclasses
