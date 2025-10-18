from __future__ import annotations
from typing import Any, Dict, List, Optional
from datetime import datetime
import sqlite3
import json
import os
import threading

_DB = os.getenv("SOCIALITE_DB", "social_agent.db")
_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(_DB)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _lock, _conn() as cx:
        cx.executescript("""
        CREATE TABLE IF NOT EXISTS user_prefs (
            user_id TEXT PRIMARY KEY,
            home_city TEXT,
            home_country TEXT,
            passions TEXT
        );
        CREATE TABLE IF NOT EXISTS subs (
            user_id TEXT PRIMARY KEY,
            frequency TEXT,
            last_sent_at TEXT
        );
        CREATE TABLE IF NOT EXISTS digests (
            user_id TEXT,
            payload TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS search_log (
            user_id TEXT,
            payload TEXT,
            count INTEGER,
            created_at TEXT
        );
        """)
        cx.commit()


# Call at import time
init()


def save_preferences(user_id: str, home_city: str | None, home_country: str | None, passions: List[str] | None):
    with _lock, _conn() as cx:
        cx.execute("""
            INSERT INTO user_prefs(user_id, home_city, home_country, passions)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET home_city=excluded.home_city,
                                             home_country=excluded.home_country,
                                             passions=excluded.passions
        """, (user_id, home_city, home_country, json.dumps(passions or [])))
        cx.commit()


def get_preferences(user_id: str) -> Dict[str, Any] | None:
    with _lock, _conn() as cx:
        cur = cx.execute(
            "SELECT * FROM user_prefs WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {
            "home_city": row["home_city"],
            "home_country": row["home_country"],
            "passions": json.loads(row["passions"] or "[]")
        }


def upsert_subscription(user_id: str, frequency: str = "weekly"):
    with _lock, _conn() as cx:
        cx.execute("""
            INSERT INTO subs(user_id, frequency, last_sent_at)
            VALUES (?, ?, NULL)
            ON CONFLICT(user_id) DO UPDATE SET frequency=excluded.frequency
        """, (user_id, frequency))
        cx.commit()


def list_subscriptions() -> List[Dict[str, Any]]:
    with _lock, _conn() as cx:
        cur = cx.execute("SELECT * FROM subs")
        rows = [dict(r) for r in cur.fetchall()]
    # enrich with prefs
    for r in rows:
        prefs = get_preferences(r["user_id"]) or {}
        r.update(prefs)
        if r.get("last_sent_at"):
            r["last_sent_at"] = datetime.fromisoformat(r["last_sent_at"])
    return rows


def bump_subscription_seen(user_id: str):
    with _lock, _conn() as cx:
        cx.execute("UPDATE subs SET last_sent_at=? WHERE user_id=?",
                   (datetime.utcnow().isoformat(), user_id))
        cx.commit()


def save_digest(user_id: str, items: List[Dict[str, Any]]):
    with _lock, _conn() as cx:
        cx.execute("INSERT INTO digests(user_id, payload, created_at) VALUES (?, ?, ?)",
                   (user_id, json.dumps(items), datetime.utcnow().isoformat()))
        cx.commit()


def pop_digest(user_id: str) -> Optional[List[Dict[str, Any]]]:
    with _lock, _conn() as cx:
        cur = cx.execute(
            "SELECT rowid, payload FROM digests WHERE user_id=? ORDER BY created_at ASC", (user_id,))
        row = cur.fetchone()
        if not row:
            return None
        cx.execute("DELETE FROM digests WHERE rowid=?", (row["rowid"],))
        cx.commit()
    return json.loads(row["payload"])


def log_event_search(user_id: str, payload: Dict[str, Any], count: int):
    with _lock, _conn() as cx:
        cx.execute("INSERT INTO search_log(user_id, payload, count, created_at) VALUES (?, ?, ?, ?)",
                   (user_id, json.dumps(payload), count, datetime.utcnow().isoformat()))
        cx.commit()
