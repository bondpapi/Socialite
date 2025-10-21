from __future__ import annotations

from typing import List, Optional
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..services.aggregator import search_events, PROVIDERS
from ..services.recommend import rank_events
from ..schemas import EventOut


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


# ---------- Routes ----------

@router.get("/_ping")
def ping() -> dict:
    """
    Lightweight healthcheck for this router.
    """
    return {"ok": True}


@router.get("/providers", response_model=ProvidersResponse)
def providers() -> ProvidersResponse:
    """
    List the available data providers registered with the aggregator.
    """
    providers_list = [
        {"name": getattr(p, "name", p.__class__.__name__)} for p in PROVIDERS
    ]
    return ProvidersResponse(providers=providers_list)


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
    Searches all registered providers in parallel.

    Example:
      GET /events/search?city=Vilnius&country=LT&days_ahead=120&start_in_days=0&include_mock=false&query=sports
    """
    try:
        now = datetime.now(timezone.utc)
        start = now + timedelta(days=start_in_days)
        end = start + timedelta(days=days_ahead)

        items = await search_events(
            city=city,
            country=country,
            start=start,
            end=end,
            query=query,
        )

        # filter mock provider if requested
        if not include_mock:
            items = [e for e in items if e.get("source") != "mock"]

        # simple ranking using default passions (can be replaced by user prefs)
        passions = ["music", "standup", "marathon", "poetry"]
        ranked = rank_events(items, passions)

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
        raise HTTPException(
            status_code=500, detail=f"events.search failed: {exc!r}")
