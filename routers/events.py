# routers/events.py
from __future__ import annotations

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError

from services.recommend import rank_events
from services.aggregator import (
    list_providers as agg_list_providers,
    search_events as agg_search_events,  # <-- async
)
from schemas import EventOut

router = APIRouter(prefix="/events", tags=["events"])


class ProvidersResponse(BaseModel):
    providers: List[Dict[str, str]]


class EventsResponse(BaseModel):
    city: str = Field(..., description="City used for search")
    country: str = Field(..., description="ISO-2 country code used for search")
    count: int
    items: List[EventOut]
    errors: List[str] = Field(default_factory=list)
    debug: Optional[Dict[str, Any]] = None


@router.get("/providers", response_model=ProvidersResponse)
def get_providers(include_mock: Optional[bool] = None) -> ProvidersResponse:
    return ProvidersResponse(providers=agg_list_providers(include_mock=include_mock))


@router.get("/search", response_model=EventsResponse)
async def search(
    *,
    city: str = Query(..., min_length=1, description="City name (non-empty)"),
    country: str = Query(
        ..., min_length=2, max_length=2, description="Country ISO-2, e.g. LT"
    ),
    days_ahead: int = Query(60, ge=1, le=3650),
    start_in_days: int = Query(0, ge=0, le=3650),
    include_mock: bool = False,
    query: Optional[str] = Query(None, description="Optional keyword filter"),
) -> EventsResponse:
    """
    Aggregated events search.

    - Validates non-empty city & ISO-2 country.
    - Awaits the async aggregator.
    - Validates each provider item into EventOut.
    - Keeps non-fatal validation errors in `errors`.
    - Applies ranking via services.recommend.rank_events.
    """
    try:
        city_clean = city.strip()
        country_clean = country.strip().upper()

        if not city_clean:
            raise HTTPException(status_code=422, detail="city must be non-empty")
        if not country_clean:
            raise HTTPException(status_code=422, detail="country must be non-empty")
        if len(country_clean) != 2:
            raise HTTPException(status_code=422, detail="country must be ISO-2 code")

        # IMPORTANT: await the aggregator (it fan-outs to providers)
        agg_payload = await agg_search_events(
            city=city_clean,
            country=country_clean,
            days_ahead=days_ahead,
            start_in_days=start_in_days,
            include_mock=include_mock,
            query=query,
        )

        raw_items: List[Dict[str, Any]] = list(agg_payload.get("items") or [])
        nonfatal_errors: List[str] = []
        valid_items: List[EventOut] = []

        # Validate/normalize each event through your schema
        for idx, e in enumerate(raw_items):
            try:
                valid_items.append(EventOut.model_validate(e))  # pydantic v2
            except ValidationError as ve:
                nonfatal_errors.append(f"item#{idx} validation failed: {ve}")

        # Optional: rank results
        try:
            valid_items = rank_events(valid_items, city=city_clean, country=country_clean)
        except Exception as _:
            # don't let ranking failures break the endpoint
            pass

        return EventsResponse(
            city=city_clean,
            country=country_clean,
            count=len(valid_items),
            items=valid_items,
            errors=nonfatal_errors,
            debug={
                "providers_used": agg_payload.get("providers_used"),
                "discovered": (agg_payload.get("debug") or {}).get("discovered"),
                "provider_errors": (agg_payload.get("debug") or {}).get("errors"),
            },
        )

    except HTTPException:
        raise
    except Exception as exc:
        # Shield the route from unexpected crashes
        raise HTTPException(status_code=500, detail=f"events.search failed: {exc!r}")
