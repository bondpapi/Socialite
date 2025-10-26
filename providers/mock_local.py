# providers/mock_local.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from providers.base import build_event, to_iso_z

KEY = "mock_local"
NAME = "Mock (Local)"

def search(
    *,
    city: str,
    country: str,
    days_ahead: int = 60,
    start_in_days: int = 0,
    query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Module-level sync search (compatible with aggregator.function-style).
    Always returns a couple of predictable mock events.
    """
    start = datetime.now(timezone.utc) + timedelta(days=start_in_days)
    e1 = build_event(
        title=f"{city} Street Food Festival",
        start_time=to_iso_z(start + timedelta(days=3, hours=18)),
        city=city, country=country,
        url=None, venue_name=f"{city} Old Town",
        category="food",
        currency="EUR", min_price=0.0,
    )
    e2 = build_event(
        title=f"{city} Live Jazz Night",
        start_time=to_iso_z(start + timedelta(days=7, hours=20)),
        city=city, country=country,
        url=None, venue_name=f"{city} Jazz Club",
        category="music",
        currency="EUR", min_price=10.0,
    )
    if query:
        q = query.lower()
        return [e for e in [e1, e2] if q in (e["title"] or "").lower()]
    return [e1, e2]
