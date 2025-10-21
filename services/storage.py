# services/storage.py
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

DB_PATH = os.getenv("DB_PATH", "social_agent.db")

# ---------- low-level helpers ----------

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@contextmanager
def _db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

# ---------- schema & init ----------

def init_db() -> None:
    """
    Creates tables if they don't exist. Safe to call repeatedly.
    """
    with _db() as conn:
        c = conn.cursor()

        # Saved events (dedupe on source + external_id)
        c.execute(
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
                saved_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (source, external_id)
            )
            """
        )

        # Optional: metrics table (some middleware uses this)
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS hits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT CURRENT_TIMESTAMP,
                route TEXT,
                status INTEGER,
                elapsed_ms REAL
            )
            """
        )

# ---------- event helpers ----------

# Map incoming event dict keys to DB columns (best-effort).
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

def _normalize_event(e: Dict[str, Any]) -> Dict[str, Any]:
    # Keep only columns we know about; missing values become None
    return {k: e.get(k) for k in _EVENT_COLUMNS}

def save_event(event: Dict[str, Any]) -> int:
    """
    Insert an event (deduped on source+external_id). Returns the row id of the existing/new row.
    """
    data = _normalize_event(event)
    if not data.get("source") or not data.get("external_id"):
        raise ValueError("save_event requires 'source' and 'external_id'")

    cols = ", ".join(data.keys())
    placeholders = ", ".join([":" + k for k in data.keys()])

    with _db() as conn:
        cur = conn.cursor()
        # Try insert; if conflict, select existing id
        cur.execute(
            f"""
            INSERT OR IGNORE INTO events ({cols}) VALUES ({placeholders})
            """,
            data,
        )
        if cur.lastrowid:  # new row
            return int(cur.lastrowid)

        # conflict -> fetch id
        cur.execute(
            "SELECT id FROM events WHERE source = ? AND external_id = ?",
            (data["source"], data["external_id"]),
        )
        row = cur.fetchone()
        return int(row["id"]) if row else 0

def get_saved_events(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    with _db() as conn:
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
