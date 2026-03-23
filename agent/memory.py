"""
WHAIP – User memory / profile store

Persists user preferences in SQLite so the agent remembers across sessions:
  - Personal data (name, address, phone)
  - Food & shopping preferences
  - Frequently used services / logins
  - Anything the agent learns during conversations

Usage:
    mem = UserMemory()
    mem.set("address", "Calle Mayor 5, Torrejón de Ardoz")
    mem.get("address")          # → "Calle Mayor 5..."
    mem.get_profile_summary()   # → human-readable string for Claude's context
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("whaip.memory")

DB_PATH = Path.home() / ".whaip" / "memory.db"


class UserMemory:

    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS profile (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        self._conn.commit()

    # ── Core get/set ───────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute(
            "SELECT value FROM profile WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return row[0]

    def set(self, key: str, value: Any) -> None:
        serialized = json.dumps(value, ensure_ascii=False)
        self._conn.execute(
            "INSERT OR REPLACE INTO profile (key, value) VALUES (?, ?)",
            (key, serialized),
        )
        self._conn.commit()
        logger.info("Memory saved: %s = %s", key, str(value)[:80])

    def delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM profile WHERE key = ?", (key,))
        self._conn.commit()

    def all(self) -> dict:
        rows = self._conn.execute("SELECT key, value FROM profile").fetchall()
        result = {}
        for key, val in rows:
            try:
                result[key] = json.loads(val)
            except Exception:
                result[key] = val
        return result

    # ── Profile helpers ────────────────────────────────────────────────────

    def get_profile_summary(self) -> str:
        """
        Returns a human-readable summary for Claude's context.
        Only includes fields that are actually set.
        """
        data = self.all()
        if not data:
            return "No hay perfil guardado todavía."

        lines = ["Perfil del usuario:"]
        field_labels = {
            "name":             "Nombre",
            "address":          "Dirección",
            "phone":            "Teléfono",
            "email":            "Email",
            "food_preferences": "Gustos de comida",
            "payment_method":   "Método de pago",
            "frequent_orders":  "Pedidos frecuentes",
            "notes":            "Notas",
        }
        for key, label in field_labels.items():
            if key in data:
                val = data[key]
                if isinstance(val, list):
                    val = ", ".join(str(v) for v in val)
                lines.append(f"  {label}: {val}")
        for key, val in data.items():
            if key not in field_labels:
                if isinstance(val, list):
                    val = ", ".join(str(v) for v in val)
                lines.append(f"  {key}: {val}")
        return "\n".join(lines)
