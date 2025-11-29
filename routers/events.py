from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError

from schemas import EventOut
from services.aggregator import (
    list_provider_diagnostics as agg_diag,
    list_providers as agg_list_providers,
    search_events as agg_search_events,
)
from services.recommend import rank_events

router = APIRouter(prefix="/events", tags=["events"])

# ---------- Responses ----------


class ProvidersResponse(BaseModel):
    providers: List[Dict[str, str]] = Field(default_factory=list)
    discovery: Optional[Dict[str, Any]] = None


class EventsResponse(BaseModel):
    city: str = Field(..., description="City used for search")
    country: str = Field(..., description="ISO-2 country code used for search")
    count: int
    items: List[EventOut]
    errors: List[str] = Field(default_factory=list)
    debug: Optional[Dict[str, Any]] = None


# ---------- Routes ----------


@router.get("/providers", response_model=ProvidersResponse)
def get_providers(include_mock: Optional[bool] = None) -> ProvidersResponse:
    """
    Return both the legacy simple list and the rich diagnostics.
    The diagnostics include: discovered_modules, loaded, skipped,
    and import errors.
    """

    try:
        diag = agg_diag()
        simple = (
            diag.get("providers") or
            agg_list_providers(include_mock=include_mock)
        )
        return ProvidersResponse(
            providers=simple,
            discovery=diag.get("discovery")
        )
    except Exception:
        return ProvidersResponse(
            providers=agg_list_providers(include_mock=include_mock)
        )


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
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
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
            raise HTTPException(
                status_code=422, detail="city must be non-empty"
            )
        if not country_clean:
            raise HTTPException(
                status_code=422, detail="country must be non-empty"
            )
        if len(country_clean) != 2:
            raise HTTPException(
                status_code=422, detail="country must be ISO-2 code"
            )

        # IMPORTANT: await the aggregator (it fan-outs to providers)
        agg_payload = await agg_search_events(
            city=city_clean,
            country=country_clean,
            days_ahead=days_ahead,
            start_in_days=start_in_days,
            include_mock=include_mock,
            query=query,
            limit=limit,
            offset=offset,
        )

        raw_items: List[Dict[str, Any]] = list(
            agg_payload.get("items") or []
        )
        nonfatal_errors: List[str] = []
        valid_items: List[EventOut] = []

        for idx, e in enumerate(raw_items):
            try:
                valid_items.append(EventOut.model_validate(e))
            except ValidationError as ve:
                nonfatal_errors.append(
                    f"item#{idx} validation failed: {ve}"
                )

        try:
            valid_items = rank_events(
                valid_items, city=city_clean, country=country_clean
            )
        except Exception:
            pass

        return EventsResponse(
            city=city_clean,
            country=country_clean,
            count=len(valid_items),
            items=valid_items,
            errors=nonfatal_errors,
            debug=agg_payload.get("debug"),
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"events.search failed: {exc!r}"
        )
