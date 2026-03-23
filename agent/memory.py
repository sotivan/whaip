"""
WHAIP – User memory / profile store

Persists user preferences in SQLite:
  - Personal data (name, address, preferences) → profile table
  - Task history for pattern learning → task_history table
"""

import json
import logging
import math
import sqlite3
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("whaip.memory")

DB_PATH = Path.home() / ".whaip" / "memory.db"

PROFILE_LABELS = {
    "name":                   "Nombre",
    "city":                   "Ciudad",
    "country":                "País",
    "home_address":           "Dirección de entrega habitual",
    "home_lat":               None,   # internal, skip in summary
    "home_lng":               None,
    "food_preferences":       "Comida favorita",
    "food_delivery_platforms":"Apps de delivery",
    "streaming_platforms":    "Plataformas de entretenimiento",
    "shopping_platforms":     "Tiendas online habituales",
    "payment_method":         "Método de pago habitual",
    "extra_notes":            "Notas adicionales",
    "elevenlabs_voice_id":    None,   # internal
    "onboarding_done":        None,   # internal
}


class UserMemory:

    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._init_db()

    def _init_db(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS profile (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS task_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                intent     TEXT NOT NULL,
                norm       TEXT NOT NULL,
                url        TEXT DEFAULT '',
                success    INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS browser_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                url         TEXT UNIQUE NOT NULL,
                domain      TEXT NOT NULL DEFAULT '',
                title       TEXT DEFAULT '',
                visit_count INTEGER DEFAULT 1,
                last_visit  TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_history_visits ON browser_history(visit_count);

            CREATE TABLE IF NOT EXISTS bookmarks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                url        TEXT UNIQUE NOT NULL,
                title      TEXT DEFAULT '',
                tags       TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS passwords (
                domain     TEXT PRIMARY KEY,
                username   TEXT NOT NULL,
                password   TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            );
        """)
        self._conn.commit()

    # ── Core get / set ─────────────────────────────────────────────────────

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
        self._conn.execute(
            "INSERT OR REPLACE INTO profile (key, value) VALUES (?, ?)",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        self._conn.commit()
        logger.info("Memory: %s = %s", key, str(value)[:80])

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

    # ── Onboarding ─────────────────────────────────────────────────────────

    def is_onboarding_done(self) -> bool:
        return self.get("onboarding_done") == "1"

    def mark_onboarding_done(self) -> None:
        self.set("onboarding_done", "1")

    # ── Profile summary for Claude ─────────────────────────────────────────

    def get_profile_summary(self) -> str:
        data = self.all()
        lines = []
        for key, label in PROFILE_LABELS.items():
            if label is None:
                continue        # internal field
            val = data.get(key)
            if not val:
                continue
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val)
            lines.append(f"{label}: {val}")
        # Frequent patterns
        frequent = self.get_frequent_tasks(5)
        if frequent:
            lines.append("Patrones frecuentes del usuario:")
            for t in frequent:
                lines.append(f"  - {t['last_intent']} (× {t['count']})")
        # Frequent sites
        sites = self.get_frequent_sites(8)
        if sites:
            lines.append("Sitios frecuentes del usuario:")
            for s in sites:
                lines.append(f"  - {s['domain']} ({s['title'] or s['url'][:50]}) ×{s['visits']}")

        # Bookmarks
        bookmarks = self.get_bookmarks()
        if bookmarks:
            lines.append("Marcadores guardados:")
            for b in bookmarks:
                tag_str = f" [{b['tags']}]" if b['tags'] else ""
                lines.append(f"  - {b['title'] or b['url'][:50]}{tag_str} → {b['url'][:60]}")

        # Saved credential domains (no passwords exposed)
        creds = self.get_credential_domains()
        if creds:
            lines.append("Credenciales guardadas para: " + ", ".join(f"{c['domain']} ({c['username']})" for c in creds))

        return "\n".join(lines) if lines else ""

    # ── Task history & pattern learning ───────────────────────────────────

    def record_task(self, intent: str, url: str = "", success: bool = True) -> None:
        norm = self._normalize(intent)
        self._conn.execute(
            "INSERT INTO task_history (intent, norm, url, success) VALUES (?, ?, ?, ?)",
            (intent[:300], norm, url[:200], 1 if success else 0),
        )
        self._conn.commit()

    def get_frequent_tasks(self, limit: int = 5) -> list:
        """Tasks repeated 2+ times, ordered by frequency."""
        rows = self._conn.execute("""
            SELECT norm, COUNT(*) AS cnt, MAX(intent) AS last_intent
            FROM task_history
            WHERE success = 1
            GROUP BY norm
            HAVING cnt >= 2
            ORDER BY cnt DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [{"norm": r[0], "count": r[1], "last_intent": r[2]} for r in rows]

    # ── Browser history ──────────────────────────────────────────────────────

    def record_visit(self, url: str, title: str = "") -> None:
        domain = self._extract_domain(url)
        if not domain:
            return
        self._conn.execute("""
            INSERT INTO browser_history (url, domain, title, visit_count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(url) DO UPDATE SET
                visit_count = visit_count + 1,
                title = COALESCE(NULLIF(excluded.title,''), title),
                last_visit = datetime('now')
        """, (url[:500], domain, title[:200]))
        self._conn.commit()

    def get_frequent_sites(self, limit: int = 10) -> list:
        rows = self._conn.execute("""
            SELECT domain, title, url, visit_count FROM browser_history
            ORDER BY visit_count DESC LIMIT ?
        """, (limit,)).fetchall()
        return [{"domain": r[0], "title": r[1], "url": r[2], "visits": r[3]} for r in rows]

    def search_history(self, query: str, limit: int = 5) -> list:
        q = f"%{query}%"
        rows = self._conn.execute("""
            SELECT url, title, visit_count FROM browser_history
            WHERE url LIKE ? OR title LIKE ? OR domain LIKE ?
            ORDER BY visit_count DESC LIMIT ?
        """, (q, q, q, limit)).fetchall()
        return [{"url": r[0], "title": r[1], "visits": r[2]} for r in rows]

    # ── Bookmarks ────────────────────────────────────────────────────────────

    def add_bookmark(self, url: str, title: str, tags: str = "") -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO bookmarks (url, title, tags) VALUES (?, ?, ?)",
            (url[:500], title[:200], tags),
        )
        self._conn.commit()
        logger.info("Bookmark saved: %s", title or url)

    def remove_bookmark(self, url: str) -> None:
        self._conn.execute("DELETE FROM bookmarks WHERE url = ?", (url,))
        self._conn.commit()

    def get_bookmarks(self) -> list:
        rows = self._conn.execute(
            "SELECT url, title, tags FROM bookmarks ORDER BY created_at DESC"
        ).fetchall()
        return [{"url": r[0], "title": r[1], "tags": r[2]} for r in rows]

    def is_bookmarked(self, url: str) -> bool:
        return bool(self._conn.execute(
            "SELECT 1 FROM bookmarks WHERE url = ?", (url,)
        ).fetchone())

    # ── Passwords ────────────────────────────────────────────────────────────

    def save_password(self, domain: str, username: str, password: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO passwords (domain, username, password, updated_at) VALUES (?, ?, ?, datetime('now'))",
            (domain, username, password),
        )
        self._conn.commit()
        logger.info("Password saved for: %s", domain)

    def get_password(self, domain: str) -> Optional[dict]:
        # Exact match
        row = self._conn.execute(
            "SELECT username, password FROM passwords WHERE domain = ?", (domain,)
        ).fetchone()
        if row:
            return {"username": row[0], "password": row[1]}
        # Partial match (e.g. domain='papajohns.es' matches stored 'papajohns.es')
        rows = self._conn.execute(
            "SELECT domain, username, password FROM passwords"
        ).fetchall()
        for stored_domain, uname, pwd in rows:
            if stored_domain in domain or domain in stored_domain:
                return {"username": uname, "password": pwd}
        return None

    def get_credential_domains(self) -> list:
        """Returns list of domains with saved passwords (no actual passwords)."""
        rows = self._conn.execute("SELECT domain, username FROM passwords ORDER BY domain").fetchall()
        return [{"domain": r[0], "username": r[1]} for r in rows]

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _extract_domain(self, url: str) -> str:
        import re
        m = re.search(r'https?://([^/?#]+)', url)
        if not m:
            return ""
        d = m.group(1).lower()
        return re.sub(r'^www\.', '', d)

    def _normalize(self, intent: str) -> str:
        import re
        t = intent.lower().strip()
        t = re.sub(r"\b\d+\b", "N", t)
        t = re.sub(r"\s+", " ", t)
        return t[:120]

    # ── Geolocation helpers ───────────────────────────────────────────────

    def set_home_location(self, lat: float, lng: float) -> None:
        self.set("home_lat", lat)
        self.set("home_lng", lng)

    def distance_from_home_km(self, lat: float, lng: float) -> Optional[float]:
        """Haversine distance in km from stored home coords. None if no home."""
        hlat = self.get("home_lat")
        hlng = self.get("home_lng")
        if hlat is None or hlng is None:
            return None
        R = 6371
        dlat = math.radians(lat - float(hlat))
        dlng = math.radians(lng - float(hlng))
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(float(hlat))) *
             math.cos(math.radians(lat)) *
             math.sin(dlng / 2) ** 2)
        return R * 2 * math.asin(math.sqrt(a))
