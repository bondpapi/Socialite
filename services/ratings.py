"""
Simple ratings persistence on SQLite (same DB you already commit).
Creates table on first import.
"""
from __future__ import annotations
import os
import sqlite3
from typing import Iterable, Optional


DB_PATH = os.getenv("SOCIALITE_DB", os.path.join(os.path.dirname(__file__), "..", "social_agent.db"))
DB_PATH = os.path.abspath(DB_PATH)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init():
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS ratings (
              user_id TEXT DEFAULT 'anon',
              external_id TEXT NOT NULL,
              rating INTEGER CHECK (rating BETWEEN 1 AND 5) NOT NULL,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (user_id, external_id)
            );

            CREATE TABLE IF NOT EXISTS saved_items (
              user_id TEXT DEFAULT 'anon',
              external_id TEXT NOT NULL,
              payload TEXT NOT NULL,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (user_id, external_id)
            );
            """
        )


def save_rating(user_id: str, external_id: str, rating: int) -> None:
    init()
    with _conn() as c:
        c.execute(
            """INSERT INTO ratings(user_id, external_id, rating)
               VALUES(?,?,?)
               ON CONFLICT(user_id, external_id) DO UPDATE SET rating=excluded.rating,
                   created_at=CURRENT_TIMESTAMP;""",
            (user_id, external_id, rating),
        )


def get_rating(user_id: str, external_id: str) -> Optional[int]:
    init()
    with _conn() as c:
        row = c.execute(
            "SELECT rating FROM ratings WHERE user_id=? AND external_id=?",
            (user_id, external_id),
        ).fetchone()
    return row[0] if row else None


def save_item(user_id: str, external_id: str, payload_json: str) -> None:
    init()
    with _conn() as c:
        c.execute(
            """INSERT INTO saved_items(user_id, external_id, payload)
               VALUES(?,?,?)
               ON CONFLICT(user_id, external_id) DO UPDATE SET payload=excluded.payload,
                   created_at=CURRENT_TIMESTAMP;""",
            (user_id, external_id, payload_json),
        )


def get_saved_items(user_id: str) -> Iterable[tuple[str, str]]:
    init()
    with _conn() as c:
        return list(
            c.execute(
                "SELECT external_id, payload FROM saved_items WHERE user_id=? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        )


def delete_saved(user_id: str, external_id: str) -> None:
    init()
    with _conn() as c:
        c.execute("DELETE FROM saved_items WHERE user_id=? AND external_id=?", (user_id, external_id))
