from __future__ import annotations

from typing import Any, Dict, List, Optional
import logging

from social_agent_ai.config import settings
from social_agent_ai.utils.http_client import HttpClient
from social_agent_ai.providers import eventbrite as eventbrite_provider
from social_agent_ai.services import web_discovery as web_discovery_service
from social_agent_ai.providers import kakava

PROVIDERS.append(("kakava", kakava.search))


logger = logging.getLogger(__name__)


def _client() -> HttpClient:
    return HttpClient(
        timeout=settings.http_timeout_seconds,
        max_retries=settings.http_max_retries,
        user_agent="Socialite/1.0 (+https://example.com)",
    )


def search_events(
    *,
    city: str,
    country: str,
    start_in_days: int,
    days_ahead: int,
    include_mock: bool = False,
    query: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fan out to providers, merge & dedupe lightly.
    All provider calls use retries + timeouts under the hood.
    """
    client = _client()
    items: List[Dict[str, Any]] = []

    # 1) Eventbrite
    try:
        ev = eventbrite_provider.search(
            client=client,
            token=settings.eventbrite_token,
            city=city,
            country=country,
            start_in_days=start_in_days,
            days_ahead=days_ahead,
            keyword=query,
        )
        items.extend(ev)
    except Exception as e:
        logger.info("Eventbrite provider error: %s", e)

    # 2) Web discovery (optional)
    if settings.enable_web_discovery:
        try:
            wd = web_discovery_service.crawl_sites(
                client=client,
                city=city,
                country=country,
                allow_domains=settings.discovery_domains or None,
                keyword=query,
                limit_per_site=25,
            )
            items.extend(wd)
        except Exception as e:
            logger.info("Web discovery error: %s", e)

    # 3) Mock (optional)
    if include_mock and not items:
        items.extend(
            [
                {
                    "source": "mock",
                    "external_id": "mock-001",
                    "title": f"Sample show in {city}",
                    "category": "Event",
                    "start_time": None,
                    "city": city,
                    "country": country,
                    "venue_name": "TBD",
                    "min_price": None,
                    "currency": None,
                    "url": None,
                }
            ]
        )

    # small dedupe by (source, external_id) or URL
    seen: set[tuple[str, str]] = set()
    deduped: List[Dict[str, Any]] = []
    for it in items:
        key = (it.get("source") or "", (it.get("external_id") or it.get("url") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)

    return {
        "city": city,
        "country": country,
        "count": len(deduped),
        "items": deduped,
    }
