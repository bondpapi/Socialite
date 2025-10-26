# services/storage.py
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DB_PATH = Path(__file__).resolve().parent.parent / "social_agent.db"

# ---------- DB helpers ----------

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _init_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS profiles (
        user_id TEXT PRIMARY KEY,
        username TEXT,
        city TEXT,
        country TEXT,
        passions TEXT,       -- JSON list
        birthday TEXT        -- ISO YYYY-MM-DD
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS saved (
        user_id TEXT,
        event_id TEXT,
        payload  TEXT,       -- JSON event
        PRIMARY KEY (user_id, event_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ratings (
        user_id TEXT,
        event_id TEXT,
        rating INTEGER,
        PRIMARY KEY (user_id, event_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS search_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts DATETIME DEFAULT CURRENT_TIMESTAMP,
        user_id TEXT,
        args    TEXT,     -- JSON of query args
        count   INTEGER
    )
    """)

    # digest outbox (server → client)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS digests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        payload TEXT      -- JSON list of cards
    )
    """)

    conn.commit()

# Ensure DB exists
with _connect() as _c:
    _init_schema(_c)


# ---------- Profiles ----------

def get_profile(user_id: str) -> Dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return None
        passions = json.loads(row["passions"]) if row["passions"] else []
        return {
            "user_id": row["user_id"],
            "username": row["username"],
            "city": row["city"],
            "country": row["country"],
            "passions": passions,
            "birthday": row["birthday"],
        }

def upsert_profile(p: Dict[str, Any]) -> Dict[str, Any]:
    passions = json.dumps(p.get("passions") or [])
    with _connect() as conn:
        conn.execute("""
        INSERT INTO profiles (user_id, username, city, country, passions, birthday)
        VALUES (:user_id, :username, :city, :country, :passions, :birthday)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            city=excluded.city,
            country=excluded.country,
            passions=excluded.passions,
            birthday=excluded.birthday
        """, {
            "user_id": p["user_id"],
            "username": p.get("username"),
            "city": p.get("city"),
            "country": p.get("country"),
            "passions": passions,
            "birthday": p.get("birthday"),
        })
        conn.commit()
    return get_profile(p["user_id"]) or p


# ---------- Saved events ----------

def save_event(user_id: str, event: Dict[str, Any]) -> None:
    event_id = event.get("id") or event.get("url") or json.dumps(event)[:64]
    with _connect() as conn:
        conn.execute("""
        INSERT OR REPLACE INTO saved (user_id, event_id, payload)
        VALUES (?, ?, ?)
        """, (user_id, event_id, json.dumps(event)))
        conn.commit()

def list_saved(user_id: str) -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT payload FROM saved WHERE user_id = ?", (user_id,)).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            try:
                out.append(json.loads(r["payload"]))
            except Exception:
                pass
        return out

def clear_saved(user_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM saved WHERE user_id = ?", (user_id,))
        conn.commit()


# ---------- Ratings ----------

def set_rating(user_id: str, event_id: str, rating: int) -> None:
    rating = max(1, min(5, int(rating)))
    with _connect() as conn:
        conn.execute("""
        INSERT OR REPLACE INTO ratings (user_id, event_id, rating)
        VALUES (?, ?, ?)
        """, (user_id, event_id, rating))
        conn.commit()


# ---------- Search log ----------

def log_search(user_id: Optional[str], args: Dict[str, Any], count: int) -> None:
    with _connect() as conn:
        conn.execute("""
        INSERT INTO search_log (user_id, args, count)
        VALUES (?, ?, ?)
        """, (user_id, json.dumps(args), int(count)))
        conn.commit()


# ---------- Digest outbox ----------

def enqueue_digest(user_id: str, cards: List[Dict[str, Any]]) -> None:
    with _connect() as conn:
        conn.execute("""
        INSERT INTO digests (user_id, payload) VALUES (?, ?)
        """, (user_id, json.dumps(cards)))
        conn.commit()

def pop_latest_digest(user_id: str) -> List[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("""
        SELECT id, payload FROM digests
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 1
        """, (user_id,)).fetchone()

        if not row:
            return []

        digest_id = row["id"]
        raw = row["payload"] or "[]"
        try:
            items = json.loads(raw)
            if not isinstance(items, list):
                items = []
        except Exception:
            items = []

        conn.execute("DELETE FROM digests WHERE id = ?", (digest_id,))
        conn.commit()
        return items
