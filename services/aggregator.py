# social_agent_ai/services/aggregator.py
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List, Iterable

from rapidfuzz import fuzz

from ..config import settings

# ---------------------------
# Provider wiring
PROVIDERS: list = []

# Mock (useful for local testing)
if getattr(settings, "enable_mock_provider", False):
    try:
        from ..providers.mock_local import MockLocalProvider
        PROVIDERS.append(MockLocalProvider())
    except Exception as e:
        print(f"[INIT] MockLocalProvider not available: {e}")

# SeatGeek (optional; often US-centric)
try:
    from ..providers.seatgeek import SeatGeekProvider as _SeatGeekProvider  # type: ignore
except Exception:
    _SeatGeekProvider = None

if _SeatGeekProvider and getattr(settings, "seatgeek_client_id", None):
    try:
        PROVIDERS.append(
            _SeatGeekProvider(
                client_id=settings.seatgeek_client_id,
                client_secret=settings.seatgeek_client_secret,
            )
        )
    except Exception as e:
        print(f"[INIT] SeatGeekProvider init failed: {e}")

# Ticketmaster
try:
    from ..providers.ticketmaster import TicketmasterProvider as _TicketmasterProvider  # type: ignore
except Exception:
    _TicketmasterProvider = None

if _TicketmasterProvider and getattr(settings, "ticketmaster_api_key", None):
    try:
        PROVIDERS.append(_TicketmasterProvider(api_key=settings.ticketmaster_api_key))
    except Exception as e:
        print(f"[INIT] TicketmasterProvider init failed: {e}")

# Eventbrite
try:
    from ..providers.eventbrite import EventbriteProvider as _EventbriteProvider  # type: ignore
except Exception:
    _EventbriteProvider = None

if _EventbriteProvider and getattr(settings, "eventbrite_token", None):
    try:
        PROVIDERS.append(_EventbriteProvider(token=settings.eventbrite_token))
    except Exception as e:
        print(f"[INIT] EventbriteProvider init failed: {e}")

# ICS feeds
try:
    from ..providers.icsfeed import ICSFeedProvider as _ICSFeedProvider  # type: ignore
except Exception:
    _ICSFeedProvider = None

if _ICSFeedProvider and getattr(settings, "ics_urls", None):
    try:
        urls = list(getattr(settings, "ics_urls", []) or [])
        if urls:
            PROVIDERS.append(_ICSFeedProvider(urls))
    except Exception as e:
        print(f"[INIT] ICSFeedProvider init failed: {e}")

# Web discovery (Tavily-backed)
try:
    from ..providers.web_discovery import WebDiscoveryProvider as _WebDiscoveryProvider  # type: ignore
except Exception:
    _WebDiscoveryProvider = None

if (
    _WebDiscoveryProvider
    and getattr(settings, "enable_web_discovery", False)
    and getattr(settings, "tavily_api_key", None)
):
    try:
        PROVIDERS.append(
            _WebDiscoveryProvider(
                tavily_key=settings.tavily_api_key,
                allow_domains=(getattr(settings, "discovery_domains", None) or None),
                max_pages=12,
            )
        )
    except Exception as e:
        print(f"[INIT] WebDiscoveryProvider init failed: {e}")

# ---------------------------
# Helpers
# ---------------------------

CITY_ALIASES = {
    "vilnius": {"vilnius", "vilniaus"},
    "kaunas": {"kaunas", "kauno"},
    "klaipėda": {"klaipėda", "klaipeda", "klaipedos"},
    "šiauliai": {"šiauliai", "siauliai"},
    "panevėžys": {"panevėžys", "panevezys"},
    "tallinn": {"tallinn", "tallinna"},
    "riga": {"rīga", "riga"},
    "berlin": {"berlin"},
}


def _infer_city_from_text(text: str, fallback: str | None = None) -> str | None:
    t = (text or "").lower()
    for city, variants in CITY_ALIASES.items():
        if any(v in t for v in variants):
            return city.capitalize()
    return fallback


def _likely_in_city(item: dict, city: str) -> bool:
    """Loose check if the requested city appears anywhere in the record."""
    blob = " ".join(
        [
            item.get("title", "") or "",
            item.get("venue_name", "") or "",
            item.get("city", "") or "",
            item.get("url", "") or "",
            item.get("category", "") or "",
        ]
    ).lower()
    return city.lower() in blob


def _as_iter(obj) -> Iterable:
    if not obj:
        return []
    if isinstance(obj, (list, tuple)):
        return obj
    return [obj]


def _sort_key(item: dict):
    # Prefer items with start_time; otherwise 0
    st = item.get("start_time")
    if not st:
        return (1, "")
    return (0, st)


# ---------------------------
# Public: active provider names
# ---------------------------

def list_providers() -> list[str]:
    return [p.__class__.__name__ for p in PROVIDERS]

# Public: main search
async def search_events(
    *,
    city: str,
    country: str,
    start: datetime | None = None,
    end: datetime | None = None,
    query: str | None = None,
) -> List[dict]:
    """
    Fan out to all configured providers, then:
      - prefer real sources (Ticketmaster/Eventbrite) if present
      - fill missing city from text
      - filter to requested city
      - dedupe by URL first, then fuzzy-title/venue
      - sort (events with dates first)
    """

    async def _run_provider(p):
        try:
            return await p.search(city=city, country=country, start=start, end=end, query=query)
        except Exception as e:
            print(f"Provider {p.__class__.__name__} error: {e}")
            return []

    results: list[dict] = []
    if not PROVIDERS:
        return results

    # Run providers concurrently
    batches = await asyncio.gather(*[_run_provider(p) for p in PROVIDERS], return_exceptions=False)
    for b in batches:
        results.extend(_as_iter(b))

    # Prefer real sources if any exist
    REAL_SOURCES = {"ticketmaster", "eventbrite"}  # extend later if needed
    real = [e for e in results if (e.get("source") or "").lower() in REAL_SOURCES]
    if real:
        results = real

    # Fill missing city from text
    enriched = []
    for e in results:
        if not e.get("city"):
            inferred = _infer_city_from_text(
                " ".join([e.get("title", "") or "", e.get("venue_name", "") or "", e.get("url", "") or ""]),
                fallback=None,
            )
            if inferred:
                e["city"] = inferred
        enriched.append(e)
    results = enriched

    # Keep items that are clearly for the requested city
    results = [
        e
        for e in results
        if (e.get("city") and e["city"].lower() == city.lower()) or _likely_in_city(e, city)
    ]

    # Drop entries without a title or url (usually low-signal web results)
    results = [e for e in results if (e.get("title") or "").strip()]

    # URL-first dedupe
    seen_urls = set()
    url_deduped: list[dict] = []
    for it in results:
        u = (it.get("url") or "").strip()
        if u:
            if u in seen_urls:
                continue
            seen_urls.add(u)
        url_deduped.append(it)
    results = url_deduped

    # Fuzzy title/venue dedupe
    deduped: list[dict] = []
    for item in results:
        if not any(
            fuzz.token_set_ratio(item.get("title", ""), d.get("title", "")) > 90
            and ((item.get("venue_name") or "").strip() == (d.get("venue_name") or "").strip())
            for d in deduped
        ):
            deduped.append(item)

    # Sort: with date first, then by start_time asc
    deduped.sort(key=_sort_key)
    return deduped
