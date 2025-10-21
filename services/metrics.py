# services/metrics.py
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "social_agent.db")

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

def init_metrics_tables() -> None:
    """
    Safe to call at startup; creates the hits table if missing.
    """
    with _db() as conn:
        conn.execute(
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

def log_hit(route: str, status: int, elapsed_ms: float) -> None:
    with _db() as conn:
        conn.execute(
            "INSERT INTO hits (route, status, elapsed_ms) VALUES (?, ?, ?)",
            (route, int(status), float(elapsed_ms)),
        )
