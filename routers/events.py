from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
import inspect

import anyio
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

# Local imports (module-relative)
from services.recommend import rank_events
from services.aggregator import list_providers  # search_events is imported inside the call helper
from schemas import EventOut

router = APIRouter(prefix="/events", tags=["events"])


# ---------- Response models ----------

class ProvidersResponse(BaseModel):
    providers: List[dict]


class EventsResponse(BaseModel):
    city: str
    country: str
    count: int
    items: List[EventOut]
    errors: List[str] = []


# ---------- Helpers ----------

async def _call_search_events(
    *,
    city: str,
    country: str,
    days_ahead: int,
    start_in_days: int,
    include_mock: bool,
    query: Optional[str],
) -> Dict[str, Any]:
    """
    Calls services.aggregator.search_events whether it's defined as
    sync or async, without blocking the event loop.
    Expects the aggregator to return a dict: {count, items, providers_used}.
    """
    
    from services.aggregator import search_events  # type: ignore

    kwargs = dict(
        city=city,
        country=country,
        days_ahead=days_ahead,
        start_in_days=start_in_days,
        include_mock=include_mock,
        query=query,
    )

    if inspect.iscoroutinefunction(search_events):
        return await search_events(**kwargs)  # type: ignore[misc]
    # Run sync function in a worker thread
    return await anyio.to_thread.run_sync(lambda: search_events(**kwargs))


# ---------- Routes ----------

@router.get("/_ping")
def ping() -> dict:
    """Lightweight healthcheck for this router."""
    return {"ok": True}


@router.get("/providers", response_model=ProvidersResponse)
def providers(include_mock: Optional[bool] = None) -> ProvidersResponse:
    """
    List the available data providers discovered by the aggregator.
    If include_mock is False, mock providers are filtered out.
    """
    provs = list_providers(include_mock=include_mock)
    return ProvidersResponse(providers=provs)


@router.get(
    "/search",
    response_model=EventsResponse,
    summary="Aggregate events from all providers",
)
async def search(
    city: str = Query(..., description="City name, e.g. 'Vilnius'"),
    country: str = Query(..., min_length=2, max_length=2,
                         description="ISO-3166 alpha-2, e.g. 'LT'"),
    days_ahead: int = Query(
        30, ge=1, le=365, description="How many days ahead to search"),
    start_in_days: int = Query(
        0, ge=0, le=365, description="Offset start by N days"),
    include_mock: bool = Query(
        False, description="Include mock data for testing"),
    query: Optional[str] = Query(
        None, description="Optional keyword filter (e.g. 'sports')"),
) -> EventsResponse:
    """
    Searches all registered providers (fan-out) and returns ranked, unified results.

    Example:
      GET /events/search?city=Vilnius&country=LT&days_ahead=120&start_in_days=0&include_mock=false&query=sports
    """
    try:
        # (We keep start/end calculation here if you want it later; the aggregator
        # handles days_ahead/start_in_days so we don't pass datetimes.)
        _now = datetime.now(timezone.utc)
        _start = _now + timedelta(days=start_in_days)
        _ = _start + timedelta(days=days_ahead)

        # Call aggregator (works whether sync or async)
        aggregated = await _call_search_events(
            city=city,
            country=country,
            days_ahead=days_ahead,
            start_in_days=start_in_days,
            include_mock=include_mock,
            query=query,
        )

        raw_items: List[Dict[str, Any]] = aggregated.get("items", [])

        # Simple ranking using default passions (swap for per-user prefs later)
        passions = ["music", "standup", "marathon", "poetry"]
        ranked = rank_events(raw_items, passions)

        return EventsResponse(
            city=city,
            country=country,
            count=len(ranked),
            items=[EventOut.parse_obj(e) for e in ranked],
            errors=[],
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"events.search failed: {exc!r}")
