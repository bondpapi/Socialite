# social_agent_ai/routers/events.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query

from ..config import settings
from ..services.aggregator import search_events

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/providers")
async def list_providers():
    # Lightweight reflection of loaded providers (for debug)
    from ..services.aggregator import PROVIDERS

    return {"providers": [p.__class__.__name__ for p in PROVIDERS]}


@router.get("/search")
async def search(
    city: str = Query(..., description="City name, e.g. 'Vilnius'"),
    country: str = Query(..., description="ISO2 country code, e.g. 'LT'"),
    query: Optional[str] = Query(
        None, description="Optional free-text (e.g., 'concert')"),
    days_ahead: int = Query(
        60, ge=1, le=365, description="Search window size"),
    start_in_days: int = Query(
        0, ge=0, le=365, description="Offset from today"),
    include_mock: bool = Query(
        True, description="Include mock provider results"),
    # New filters
    category: Optional[str] = Query(None, description="Filter by category"),
    min_price: Optional[float] = Query(
        None, ge=0, description="Minimum price"),
    max_price: Optional[float] = Query(
        None, ge=0, description="Maximum price"),
    radius_km: Optional[int] = Query(
        None, ge=1, le=300, description="Distance radius (km) if coords exist)"),
    sort: str = Query("date", regex="^(date|price|price_desc)$"),
):
    """
    Returns a normalized list of events across providers.
    """
    # Build time window based on app timezone (string)
    try:
        # naive now() is fine; providers generally expect UTC-ish ISO strings; we pass datetimes around.
        now = datetime.now()
    except Exception:
        now = datetime.utcnow()

    start = now + timedelta(days=int(start_in_days))
    end = start + timedelta(days=int(days_ahead))

    # NOTE: If you later add geocoding for city_lat/lon, pass it here to enforce radius filters accurately.
    items, provider_errors = await search_events(
        city=city,
        country=country,
        start=start,
        end=end,
        query=query,
        category=category,
        min_price=min_price,
        max_price=max_price,
        radius_km=radius_km,
        city_lat=None,  # set if you have coords
        city_lon=None,  # set if you have coords
        sort=sort,
        include_mock=include_mock,
    )

    return {
        "city": city,
        "country": country,
        "count": len(items),
        "items": items,
        "provider_errors": provider_errors,  # non-fatal info
    }
