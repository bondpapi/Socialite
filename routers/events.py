# social_agent_ai/routers/events.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query

from ..services import aggregator

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/providers")
def get_providers():
    return {"providers": aggregator.list_providers()}


@router.get("/search")
async def search_events(
    city: str,
    country: str,
    days_ahead: int = 90,
    start_in_days: int = 0,
    query: Optional[str] = None,
    include_mock: bool = False,  # kept for compatibility if your UI sends it
    debug: bool = Query(False, description="Include per-provider timings and errors"),
):
    """
    Search events across all configured providers.
    """
    now = datetime.utcnow()
    start = now + timedelta(days=start_in_days)
    end = start + timedelta(days=days_ahead)

    items, diag = await aggregator.search_events(
        city=city,
        country=country,
        start=start,
        end=end,
        query=query,
        debug=debug,
    )

    payload = {
        "city": city,
        "country": country,
        "count": len(items),
        "items": items,
    }
    if debug:
        payload["debug"] = diag
    return payload
