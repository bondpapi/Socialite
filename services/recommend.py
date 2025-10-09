from __future__ import annotations
from typing import Iterable

# super-simple scorer: prefer category/keywords matches


def score_event(event: dict, passions: list[str]) -> float:
    base = 0.0
    title = (event.get("title") or "").lower()
    category = (event.get("category") or "").lower()
    for p in passions:
        if p.lower() in title or p.lower() in category:
            base += 1.0
    # cheaper tickets get a tiny bonus
    price = event.get("min_price")
    if isinstance(price, (int, float)):
        base += max(0.0, 1.0 - min(price, 100) / 100.0) * 0.25
    return base


def rank_events(events: list[dict], passions: list[str]) -> list[dict]:
    return sorted(events, key=lambda e: score_event(e, passions), reverse=True)
