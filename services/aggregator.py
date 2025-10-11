# social_agent_ai/services/aggregator.py
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from math import asin, cos, radians, sin, sqrt
from typing import Any, Dict, Iterable, List, Optional, Tuple

from rapidfuzz import fuzz

from ..config import settings

# ---------------------
# Provider bootstrapping
# ---------------------

PROVIDERS: List[Any] = []

# Optional Mock
if getattr(settings, "enable_mock_provider", True):
    try:
        from ..providers.mock_local import MockLocalProvider

        PROVIDERS.append(MockLocalProvider())
    except Exception:
        pass

# Optional SeatGeek
try:
    from ..providers.seatgeek import SeatGeekProvider as _SeatGeekProvider  # type: ignore
except Exception:
    _SeatGeekProvider = None

if _SeatGeekProvider and settings.seatgeek_client_id:
    PROVIDERS.append(
        _SeatGeekProvider(
            client_id=settings.seatgeek_client_id,
            client_secret=settings.seatgeek_client_secret,
        )
    )

# Optional Ticketmaster
try:
    from ..providers.ticketmaster import TicketmasterProvider as _TicketmasterProvider  # type: ignore
except Exception:
    _TicketmasterProvider = None

if _TicketmasterProvider and getattr(settings, "ticketmaster_api_key", None):
    PROVIDERS.append(_TicketmasterProvider(
        api_key=settings.ticketmaster_api_key))

# Optional Eventbrite
try:
    from ..providers.eventbrite import EventbriteProvider as _EventbriteProvider  # type: ignore
except Exception:
    _EventbriteProvider = None

if _EventbriteProvider and getattr(settings, "eventbrite_token", None):
    PROVIDERS.append(_EventbriteProvider(token=settings.eventbrite_token))

# Optional ICS feeds
try:
    from ..providers.icsfeed import ICSFeedProvider as _ICSFeedProvider  # type: ignore
except Exception:
    _ICSFeedProvider = None

if _ICSFeedProvider and settings.ics_urls:
    PROVIDERS.append(_ICSFeedProvider(settings.ics_urls))

# Optional Web Discovery (Tavily)
try:
    from ..providers.web_discovery import WebDiscoveryProvider as _WebDiscoveryProvider  # type: ignore
except Exception:
    _WebDiscoveryProvider = None

if (
    _WebDiscoveryProvider
    and settings.enable_web_discovery
    and settings.tavily_api_key
):
    PROVIDERS.append(
        _WebDiscoveryProvider(
            tavily_key=settings.tavily_api_key,
            allow_domains=settings.discovery_domains or None,
            max_pages=12,
        )
    )


# ---------------------
# Helpers
# ---------------------


def _parse_iso_dt(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        # handle ...Z
        if val.endswith("Z"):
            val = val.replace("Z", "+00:00")
        return datetime.fromisoformat(val)
    except Exception:
        return None


def _price_to_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except Exception:
        return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # Earth radius in km
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * \
        cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return R * c


def _supports_kwargs(fn: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Filter kwargs to only those the provider's search() supports."""
    try:
        sig = inspect.signature(fn)
        keep = {}
        for name, param in sig.parameters.items():
            if name in payload:
                keep[name] = payload[name]
        return keep
    except Exception:
        # Fallback: pass the minimal core fields only
        base = {
            k: v
            for k, v in payload.items()
            if k in {"city", "country", "start", "end", "query"}
        }
        return base


# ---------------------
# Core search
# ---------------------


async def search_events(
    *,
    city: str,
    country: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    query: Optional[str] = None,
    # New filters
    category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    radius_km: Optional[int] = None,
    city_lat: Optional[float] = None,
    city_lon: Optional[float] = None,
    sort: str = "date",  # "date" | "price" | "price_desc"
    include_mock: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """
    Returns (items, provider_errors)

    Each item should match the normalized schema fields we use in the UI:
    {
      "source": "ticketmaster" | "eventbrite" | "web" | "mock" | ...,
      "external_id": "...",
      "title": "...",
      "category": "...",
      "start_time": "ISO8601",
      "city": "Vilnius",
      "country": "LT",
      "venue_name": "...",
      "min_price": 20.0 or None,
      "currency": "EUR",
      "url": "https://..."
      # optional: "latitude","longitude"
    }
    """
    provider_errors: List[Dict[str, str]] = []

    # Build a common payload; we'll filter per provider via signature
    base_payload: Dict[str, Any] = dict(
        city=city, country=country, start=start, end=end, query=query
    )

    async def _call_provider(p: Any) -> List[Dict[str, Any]]:
        try:
            kw = _supports_kwargs(p.search, base_payload)
            items = await p.search(**kw)  # type: ignore
            return items or []
        except Exception as e:
            provider_errors.append(
                {"provider": p.__class__.__name__, "message": str(e)}
            )
            return []

    # Run providers concurrently
    results_nested = await asyncio.gather(*[_call_provider(p) for p in PROVIDERS])
    results: List[Dict[str, Any]] = [
        it for sub in results_nested for it in sub]

    # Optionally drop mock
    if not include_mock:
        results = [x for x in results if (
            x.get("source") or "").lower() != "mock"]

    # Prefer real sources if any are present
    REAL_SOURCES = {"ticketmaster", "eventbrite", "seatgeek"}
    real = [e for e in results if (
        e.get("source") or "").lower() in REAL_SOURCES]
    if real:
        results = real

    # ---------
    # Filtering
    # ---------
    if category:
        cat_l = category.strip().lower()
        results = [
            r
            for r in results
            if (
                (r.get("category") and cat_l in str(r["category"]).lower())
                or (cat_l in str(r.get("title", "")).lower())
            )
        ]

    if (min_price is not None) or (max_price is not None):
        filtered: List[Dict[str, Any]] = []
        for r in results:
            price = _price_to_float(r.get("min_price"))
            if price is None:
                # If price unknown, keep it (or set a policy to drop). We'll keep.
                filtered.append(r)
                continue
            if (min_price is not None and price < float(min_price)) or (
                max_price is not None and price > float(max_price)
            ):
                continue
            filtered.append(r)
        results = filtered

    if radius_km and city_lat is not None and city_lon is not None:
        within: List[Dict[str, Any]] = []
        for r in results:
            lat = r.get("latitude") or r.get("lat")
            lon = r.get("longitude") or r.get("lon")
            if lat is None or lon is None:
                # keep if unknown coordinates
                within.append(r)
                continue
            try:
                d = _haversine_km(float(city_lat), float(
                    city_lon), float(lat), float(lon))
                if d <= float(radius_km):
                    within.append(r)
            except Exception:
                within.append(r)
        results = within

    # -------------
    # De-duplication
    # -------------
    #
    # Rules:
    # - fuzzy title similarity > 85 AND same venue -> dup
    # - If dates exist, require within ±1 day window
    #
    deduped: List[Dict[str, Any]] = []
    for item in results:
        t = (item.get("title") or "").strip()
        venue = (item.get("venue_name") or "").strip()
        dt = _parse_iso_dt(item.get("start_time"))
        is_dup = False
        for d in deduped:
            t2 = (d.get("title") or "").strip()
            venue2 = (d.get("venue_name") or "").strip()
            score = fuzz.token_set_ratio(t, t2)
            if score >= 85 and venue and venue2 and venue == venue2:
                # Check date proximity if both present
                dt2 = _parse_iso_dt(d.get("start_time"))
                if (dt and dt2 and abs((dt - dt2).days) <= 1) or (dt is None or dt2 is None):
                    is_dup = True
                    break
        if not is_dup:
            deduped.append(item)
    results = deduped

    # -----
    # Sort
    # -----
    sort_key = (sort or "date").lower()
    if sort_key == "price":
        results.sort(
            key=lambda r: (_price_to_float(r.get("min_price"))
                           is None, _price_to_float(r.get("min_price")) or 0.0)
        )
    elif sort_key == "price_desc":
        results.sort(
            key=lambda r: (_price_to_float(r.get("min_price"))
                           is None, -(_price_to_float(r.get("min_price")) or 0.0))
        )
    else:
        # default by date ascending
        results.sort(
            key=lambda r: (_parse_iso_dt(r.get("start_time")) is None, _parse_iso_dt(
                r.get("start_time")) or datetime.max.replace(tzinfo=timezone.utc))
        )

    return results, provider_errors
