from __future__ import annotations

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.recommend import rank_events
from services.aggregator import list_providers as agg_list_providers, search_events as agg_search_events
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
    provs = agg_list_providers(include_mock=include_mock)
    return ProvidersResponse(providers=provs)


@router.get(
    "/search",
    response_model=EventsResponse,
    summary="Aggregate events from all providers",
)
async def search(
    city: str = Query(..., description="City name, e.g. 'Vilnius'"),
    country: str = Query(..., min_length=2, max_length=2, description="ISO-3166 alpha-2, e.g. 'LT'"),
    days_ahead: int = Query(30, ge=1, le=365, description="How many days ahead to search"),
    start_in_days: int = Query(0, ge=0, le=365, description="Offset start by N days"),
    include_mock: bool = Query(False, description="Include mock data for testing"),
    query: Optional[str] = Query(None, description="Optional keyword filter (e.g. 'sports')"),
) -> EventsResponse:
    """
    Fan-out via the async aggregator and return ranked, unified results.
    Provider failures are represented in `errors` instead of causing a 500.
    """
    try:
        aggregated: Dict[str, Any] = await agg_search_events(
            city=city,
            country=country,
            days_ahead=days_ahead,
            start_in_days=start_in_days,
            include_mock=include_mock,
            query=query,
        )

        raw_items: List[Dict[str, Any]] = aggregated.get("items", []) or []

        # Pull any provider-level errors injected by the aggregator
        nonfatal_errors: List[str] = []
        for e in raw_items:
            if isinstance(e, dict) and e.get("category") == "provider_error" and e.get("error"):
                nonfatal_errors.append(str(e["error"]))

        # Simple ranking (swap in user prefs later)
        passions = ["music", "standup", "marathon", "poetry"]
        ranked = rank_events(raw_items, passions)

        return EventsResponse(
            city=city,
            country=country,
            count=len(ranked),
            items=[EventOut.parse_obj(e) for e in ranked],
            errors=nonfatal_errors,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"events.search failed: {exc!r}")
