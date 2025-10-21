from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List

# Put DB alongside your repo root, same as services/metrics.py
DB_PATH = Path(__file__).resolve().parent.parent / "social_agent.db"

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# -------------------- schema / init --------------------

def init_db() -> None:
    """
    Create tables needed by the app. Safe to call multiple times.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        cur = conn.cursor()
        # Saved events table. We dedupe by (source, external_id)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                external_id TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT,
                start_time TEXT,
                city TEXT,
                country TEXT,
                venue_name TEXT,
                min_price REAL,
                currency TEXT,
                url TEXT,
                saved_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (source, external_id)
            )
            """
        )
        conn.commit()

# -------------------- helpers --------------------

_EVENT_COLUMNS = {
    "source",
    "external_id",
    "title",
    "category",
    "start_time",
    "city",
    "country",
    "venue_name",
    "min_price",
    "currency",
    "url",
}

def _sanitize_event(e: Dict[str, Any]) -> Dict[str, Any]:
    # Keep only known columns; missing values become None
    return {k: e.get(k) for k in _EVENT_COLUMNS}

def save_event(event: Dict[str, Any]) -> int:
    """
    Insert (or no-op if duplicate) and return the row id.
    Requires 'source' and 'external_id'.
    """
    data = _sanitize_event(event)
    if not data.get("source") or not data.get("external_id"):
        raise ValueError("save_event requires 'source' and 'external_id'")

    cols = ", ".join(data.keys())
    placeholders = ", ".join([":" + k for k in data.keys()])

    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"INSERT OR IGNORE INTO events ({cols}) VALUES ({placeholders})",
            data,
        )
        if cur.lastrowid:
            return int(cur.lastrowid)

        # already existed; return existing id
        cur.execute(
            "SELECT id FROM events WHERE source = ? AND external_id = ?",
            (data["source"], data["external_id"]),
        )
        row = cur.fetchone()
        return int(row["id"]) if row else 0

def get_saved_events(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, source, external_id, title, category, start_time, city, country,
                   venue_name, min_price, currency, url, saved_at
            FROM events
            ORDER BY saved_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]
