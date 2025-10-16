from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DB_PATH = Path(__file__).resolve().parent.parent / "social_agent.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_metrics_tables() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS http_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts DATETIME DEFAULT CURRENT_TIMESTAMP,
                route TEXT,
                method TEXT,
                status INTEGER,
                duration_ms INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts DATETIME DEFAULT CURRENT_TIMESTAMP,
                model TEXT,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                total_tokens INTEGER,
                est_cost_usd REAL
            )
            """
        )
        conn.commit()


def log_http(route: str, method: str, status: int, duration_ms: int) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO http_metrics (route, method, status, duration_ms) VALUES (?, ?, ?, ?)",
            (route, method, int(status), int(duration_ms)),
        )
        conn.commit()


def summary_http(limit_routes: int = 50) -> Dict[str, Any]:
    """
    Returns aggregate per-route metrics + totals.
    """
    with _connect() as conn:
        totals = conn.execute(
            """
            SELECT
                COUNT(*) as requests,
                AVG(duration_ms) as avg_ms,
                SUM(CASE WHEN status BETWEEN 200 AND 299 THEN 1 ELSE 0 END) AS s2xx,
                SUM(CASE WHEN status BETWEEN 400 AND 499 THEN 1 ELSE 0 END) AS s4xx,
                SUM(CASE WHEN status >= 500 THEN 1 ELSE 0 END) AS s5xx
            FROM http_metrics
            """
        ).fetchone()

        rows = conn.execute(
            """
            SELECT
                route,
                COUNT(*) as requests,
                AVG(duration_ms) as avg_ms,
                SUM(CASE WHEN status BETWEEN 200 AND 299 THEN 1 ELSE 0 END) AS s2xx,
                SUM(CASE WHEN status BETWEEN 400 AND 499 THEN 1 ELSE 0 END) AS s4xx,
                SUM(CASE WHEN status >= 500 THEN 1 ELSE 0 END) AS s5xx
            FROM http_metrics
            GROUP BY route
            ORDER BY requests DESC
            LIMIT ?
            """,
            (limit_routes,),
        ).fetchall()

    per_route = [
        dict(
            route=r["route"],
            requests=r["requests"],
            avg_ms=round(r["avg_ms"] or 0, 1),
            s2xx=r["s2xx"] or 0,
            s4xx=r["s4xx"] or 0,
            s5xx=r["s5xx"] or 0,
        )
        for r in rows
    ]

    return dict(
        totals=dict(
            requests=totals["requests"] or 0,
            avg_ms=round(totals["avg_ms"] or 0, 1),
            s2xx=totals["s2xx"] or 0,
            s4xx=totals["s4xx"] or 0,
            s5xx=totals["s5xx"] or 0,
        ),
        routes=per_route,
    )


def timeline_http(last_n: int = 300) -> List[Dict[str, Any]]:
    """
    Recent rolling window: timestamp + duration & status. Good for charts.
    """
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT ts, route, status, duration_ms
            FROM http_metrics
            ORDER BY id DESC
            LIMIT ?
            """,
            (last_n,),
        ).fetchall()

    out = []
    for r in rows[::-1]:
        out.append(
            dict(
                ts=r["ts"],
                route=r["route"],
                status=r["status"],
                duration_ms=r["duration_ms"],
            )
        )
    return out


PRICE_PER_1K = {
    # Example prices — adjust to your models
    # "gpt-4o-mini": dict(prompt=0.15, completion=0.60),  # $/1K tokens
    # "gpt-4o": dict(prompt=5.00, completion=15.00),
}

def log_llm_usage(model: str, prompt_tokens: int, completion_tokens: int) -> None:
    p = PRICE_PER_1K.get(model)
    est = 0.0
    if p:
        est = (prompt_tokens / 1000.0) * p["prompt"] + (completion_tokens / 1000.0) * p["completion"]
    total = prompt_tokens + completion_tokens
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO llm_usage (model, prompt_tokens, completion_tokens, total_tokens, est_cost_usd)
            VALUES (?, ?, ?, ?, ?)
            """,
            (model, int(prompt_tokens), int(completion_tokens), int(total), float(est)),
        )
        conn.commit()


def summary_llm() -> Dict[str, Any]:
    with _connect() as conn:
        totals = conn.execute(
            """
            SELECT
                COUNT(*) as calls,
                SUM(prompt_tokens) as pt,
                SUM(completion_tokens) as ct,
                SUM(total_tokens) as tt,
                SUM(est_cost_usd) as cost
            FROM llm_usage
            """
        ).fetchone()

        by_model = conn.execute(
            """
            SELECT model,
                   COUNT(*) as calls,
                   SUM(total_tokens) as tt,
                   SUM(est_cost_usd) as cost
            FROM llm_usage
            GROUP BY model
            ORDER BY calls DESC
            """
        ).fetchall()

    return dict(
        totals=dict(
            calls=totals["calls"] or 0,
            prompt_tokens=totals["pt"] or 0,
            completion_tokens=totals["ct"] or 0,
            total_tokens=totals["tt"] or 0,
            est_cost_usd=round(totals["cost"] or 0.0, 4),
        ),
        models=[
            dict(model=r["model"], calls=r["calls"], total_tokens=r["tt"] or 0, est_cost_usd=round(r["cost"] or 0.0, 4))
            for r in by_model
        ],
    )
