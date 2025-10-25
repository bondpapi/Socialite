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


def _init():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        cur = conn.cursor()

        # user preferences (one row per user)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_prefs (
            user_id TEXT PRIMARY KEY,
            home_city TEXT,
            home_country TEXT,
            passions TEXT      -- JSON array of strings
        )
        """)

        # subscriptions (weekly/daily)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id TEXT PRIMARY KEY,
            frequency TEXT CHECK(frequency in ('daily','weekly')) NOT NULL DEFAULT 'weekly'
        )
        """)

        # saved events (users can save multiple)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS saved_events (
            user_id TEXT NOT NULL,
            event_key TEXT NOT NULL,
            payload   TEXT,     -- JSON blob of the event
            ts DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, event_key)
        )
        """)

        # lightweight search log for metrics
        cur.execute("""
        CREATE TABLE IF NOT EXISTS search_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP,
            user_id TEXT,
            args    TEXT,     -- JSON of query args
            count   INTEGER
        )
        """)

        conn.commit()


_init()


# ---------- Preferences ----------

def save_preferences(
    *,
    user_id: str,
    home_city: Optional[str] = None,
    home_country: Optional[str] = None,
    passions: Optional[List[str]] = None,
) -> None:
    """Upsert preferences for a user."""
    passions_json = json.dumps(passions or [])
    with _connect() as conn:
        conn.execute("""
            INSERT INTO user_prefs (user_id, home_city, home_country, passions)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                home_city=excluded.home_city,
                home_country=excluded.home_country,
                passions=excluded.passions
        """, (user_id, home_city, home_country, passions_json))
        conn.commit()


def get_preferences(user_id: str) -> Dict[str, Any]:
    """Return preferences dict; empty dict if none."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT home_city, home_country, passions FROM user_prefs WHERE user_id = ?",
            (user_id,)
        ).fetchone()

    if not row:
        return {}

    passions = []
    if row["passions"]:
        try:
            passions = json.loads(row["passions"])
        except Exception:
            passions = []

    return {
        "home_city": row["home_city"],
        "home_country": row["home_country"],
        "passions": passions,
    }


# ---------- Subscriptions ----------

def upsert_subscription(user_id: str, *, frequency: str = "weekly") -> None:
    with _connect() as conn:
        conn.execute("""
            INSERT INTO subscriptions (user_id, frequency)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET frequency=excluded.frequency
        """, (user_id, frequency))
        conn.commit()


def get_subscription(user_id: str) -> Optional[str]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT frequency FROM subscriptions WHERE user_id = ?",
            (user_id,)
        ).fetchone()
    return row["frequency"] if row else None


# ---------- Saved events ----------

def list_saved(user_id: str) -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT event_key, payload, ts FROM saved_events WHERE user_id = ? ORDER BY ts DESC",
            (user_id,)
        ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        payload = {}
        if r["payload"]:
            try:
                payload = json.loads(r["payload"])
            except Exception:
                payload = {}
        out.append({"event_key": r["event_key"], "payload": payload, "ts": r["ts"]})
    return out


def add_saved(user_id: str, event_key: str, event_payload: Dict[str, Any]) -> None:
    with _connect() as conn:
        conn.execute("""
            INSERT INTO saved_events (user_id, event_key, payload)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, event_key) DO UPDATE SET payload=excluded.payload
        """, (user_id, event_key, json.dumps(event_payload)))
        conn.commit()


def delete_saved(user_id: str, event_key: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM saved_events WHERE user_id = ? AND event_key = ?",
            (user_id, event_key)
        )
        conn.commit()


# ---------- Metrics / logging ----------

def log_event_search(user_id: str, args: Dict[str, Any], count: int) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO search_log (user_id, args, count) VALUES (?, ?, ?)",
            (user_id, json.dumps(args), int(count))
        )
        conn.commit()
