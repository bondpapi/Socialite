# social_agent_ai/services/aggregator.py
from __future__ import annotations

import time
from datetime import datetime
from typing import List, Tuple, Dict, Any

from rapidfuzz import fuzz
from ..config import settings

PROVIDERS: list = []

# Optional mock
if settings.enable_mock_provider:
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
    PROVIDERS.append(_TicketmasterProvider(api_key=settings.ticketmaster_api_key))

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


def list_providers() -> List[str]:
    return [p.__class__.__name__ for p in PROVIDERS]


async def search_events(
    *,
    city: str,
    country: str,
    start: datetime | None = None,
    end: datetime | None = None,
    query: str | None = None,
    debug: bool = False,
) -> Tuple[List[dict], List[Dict[str, Any]]]:
    """
    Returns (items, diagnostics)
    diagnostics: list of {provider, ms, ok, count, error?}
    """
    results: list[dict] = []
    diag: list[Dict[str, Any]] = []

    for p in PROVIDERS:
        t0 = time.perf_counter()
        name = p.__class__.__name__
        ok = True
        count = 0
        err = None
        try:
            items = await p.search(
                city=city, country=country, start=start, end=end, query=query
            )
            count = len(items)
            results.extend(items)
        except Exception as e:
            ok = False
            err = f"{type(e).__name__}: {e}"
        finally:
            ms = round((time.perf_counter() - t0) * 1000.0, 1)
            diag.append(
                {
                    "provider": name,
                    "ms": ms,
                    "ok": ok,
                    "count": count,
                    **({"error": err} if err else {}),
                }
            )

    # Prefer real sources if any are present
    REAL_SOURCES = {"ticketmaster", "eventbrite"}
    real = [e for e in results if e.get("source") in REAL_SOURCES]
    if real:
        results = real

    # naive dedupe by title+venue
    deduped: list[dict] = []
    for item in results:
        if not any(
            fuzz.token_set_ratio(item.get("title", ""), d.get("title", "")) > 90
            and (item.get("venue_name") == d.get("venue_name"))
            for d in deduped
        ):
            deduped.append(item)

    return (deduped, diag if debug else [])
