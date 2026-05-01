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


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


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

    # Migration-safe additions for the FastHTML UI.
    _add_column_if_missing(conn, "profiles", "days_ahead", "INTEGER DEFAULT 120")
    _add_column_if_missing(conn, "profiles", "start_in_days", "INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "profiles", "keywords", "TEXT")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS saved (
        user_id TEXT,
        event_id TEXT,
        payload  TEXT,
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
        args    TEXT,
        count   INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS digests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        payload TEXT
    )
    """)

    conn.commit()


# ---------- Profiles ----------


def get_profile(user_id: str) -> Dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        if not row:
            return None

        try:
            passions = json.loads(row["passions"]) if row["passions"] else []
        except Exception:
            passions = []

        return {
            "user_id": row["user_id"],
            "username": row["username"] or "demo",
            "city": row["city"] or "",
            "country": (row["country"] or "LT").upper()[:2],
            "passions": passions,
            "birthday": row["birthday"],
            "days_ahead": int(row["days_ahead"] or 120),
            "start_in_days": int(row["start_in_days"] or 0),
            "keywords": row["keywords"],
        }


def upsert_profile(p: Dict[str, Any]) -> Dict[str, Any]:
    user_id = p["user_id"]

    existing = get_profile(user_id) or {}

    merged = {
        "user_id": user_id,
        "username": p.get("username", existing.get("username") or "demo"),
        "city": p.get("city", existing.get("city") or ""),
        "country": p.get("country", existing.get("country") or "LT"),
        "passions": p.get("passions", existing.get("passions") or []),
        "birthday": p.get("birthday", existing.get("birthday")),
        "days_ahead": p.get("days_ahead", existing.get("days_ahead") or 120),
        "start_in_days": p.get("start_in_days", existing.get("start_in_days") or 0),
        "keywords": p.get("keywords", existing.get("keywords")),
    }

    merged["country"] = str(merged["country"] or "LT").strip().upper()[:2]

    try:
        merged["days_ahead"] = int(merged["days_ahead"] or 120)
    except Exception:
        merged["days_ahead"] = 120

    try:
        merged["start_in_days"] = int(merged["start_in_days"] or 0)
    except Exception:
        merged["start_in_days"] = 0

    if isinstance(merged["passions"], str):
        passions_list = [
            x.strip() for x in merged["passions"].split(",") if x.strip()
        ]
    else:
        passions_list = list(merged["passions"] or [])

    passions_json = json.dumps(passions_list)

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO profiles (
                user_id,
                username,
                city,
                country,
                passions,
                birthday,
                days_ahead,
                start_in_days,
                keywords
            )
            VALUES (
                :user_id,
                :username,
                :city,
                :country,
                :passions,
                :birthday,
                :days_ahead,
                :start_in_days,
                :keywords
            )
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                city=excluded.city,
                country=excluded.country,
                passions=excluded.passions,
                birthday=excluded.birthday,
                days_ahead=excluded.days_ahead,
                start_in_days=excluded.start_in_days,
                keywords=excluded.keywords
            """,
            {
                "user_id": merged["user_id"],
                "username": merged["username"],
                "city": merged["city"],
                "country": merged["country"],
                "passions": passions_json,
                "birthday": merged["birthday"],
                "days_ahead": merged["days_ahead"],
                "start_in_days": merged["start_in_days"],
                "keywords": merged["keywords"],
            },
        )
        conn.commit()

    return get_profile(user_id) or merged


def get_preferences(user_id: str) -> Dict[str, Any]:
    profile = get_profile(user_id)

    if not profile:
        return {
            "home_city": None,
            "home_country": None,
            "city": None,
            "country": None,
            "passions": [],
            "days_ahead": 120,
            "start_in_days": 0,
            "keywords": None,
        }

    return {
        "home_city": profile.get("city"),
        "home_country": profile.get("country"),
        "city": profile.get("city"),
        "country": profile.get("country"),
        "passions": profile.get("passions") or [],
        "days_ahead": profile.get("days_ahead") or 120,
        "start_in_days": profile.get("start_in_days") or 0,
        "keywords": profile.get("keywords"),
    }


def save_preferences(
    user_id: str,
    home_city: Optional[str] = None,
    home_country: Optional[str] = None,
    passions: Optional[List[str]] = None,
) -> None:
    """
    Compatibility helper for the older agent preference tools.
    Preserves existing profile values.
    """
    profile_data: Dict[str, Any] = {"user_id": user_id}

    if home_city is not None:
        profile_data["city"] = home_city

    if home_country is not None:
        profile_data["country"] = home_country

    if passions is not None:
        profile_data["passions"] = passions

    upsert_profile(profile_data)


def upsert_subscription(user_id: str, frequency: str = "weekly") -> None:
    """
    Placeholder for subscription management.
    Currently a no-op; implement when subscription table is added.
    """
    # TODO: Add subscriptions table to schema
    pass


# ---------- Saved events ----------


def save_event(user_id: str, event: Dict[str, Any]) -> None:
    event_id = (
        event.get("id") or event.get("url") or json.dumps(event)[:64]
    )
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO saved (user_id, event_id, payload)
            VALUES (?, ?, ?)
            """,
            (user_id, event_id, json.dumps(event)),
        )
        conn.commit()


def list_saved(user_id: str) -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT payload FROM saved WHERE user_id = ?", (user_id,)
        ).fetchall()
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


def log_event_search(user_id: str, params: Dict[str, Any], count: int) -> None:
    """
    Log an event search for analytics or future recommendations.

    This is a safe no-op stub for now; can later wire it to a real
    SQLite table if you want (e.g. event_searches).
    """
    # implementation if I want to persist:
    # with get_conn() as conn:
    #     conn.execute(
    #         "INSERT INTO event_searches (user_id, params_json, result_count, created_at) "
    #         "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
    #         (user_id, json.dumps(params), count),
    #     )
    # For now, just ignore to avoid breaking the agent.
    return None


def log_agent_error(user_id: str, message: str) -> None:
    """
    Optionally log agent-level errors. Currently a safe no-op.
    """
    # Same pattern: can persist to a table or a log file later.
    return None
