from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DB_PATH = Path(__file__).resolve().parent.parent / "social_agent.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_events (
                user_id TEXT NOT NULL,
                event_key TEXT NOT NULL,
                data_json TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, event_key)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                display_name TEXT
            )
            """
        )
        conn.commit()


def upsert_user(user_id: str, display_name: Optional[str]) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, display_name)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET display_name=excluded.display_name
            """,
            (user_id, display_name),
        )
        conn.commit()


def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT user_id, display_name FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return None
        return {"user_id": row["user_id"], "display_name": row["display_name"]}


def save_event(user_id: str, event_key: str, data: Dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO saved_events (user_id, event_key, data_json)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, event_key) DO UPDATE SET data_json=excluded.data_json
            """,
            (user_id, event_key, payload),
        )
        conn.commit()


def delete_event(user_id: str, event_key: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM saved_events WHERE user_id=? AND event_key=?", (user_id, event_key))
        conn.commit()


def list_saved(user_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT event_key, data_json, created_at
            FROM saved_events WHERE user_id=?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            try:
                data = json.loads(r["data_json"])
            except Exception:
                data = {}
            data["_event_key"] = r["event_key"]
            data["_saved_at"] = r["created_at"]
            out.append(data)
        return out
