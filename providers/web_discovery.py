from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional
import logging
import re
from datetime import datetime

import requests

from social_agent_ai.utils.http_client import HttpClient

logger = logging.getLogger(__name__)

DEFAULT_SITES = [
    # Lithuanian ticket portals (examples)
    "bilietai.lt",
    "piletilevi.ee",
    "bilesuserviss.lv",
    "tiketa.lt",
    "kakava.lt",
]


def _looks_like_event_title(text: str) -> bool:
    if not text:
        return False
    # super simple heuristic
    bad = {"cookies", "privacy", "login", "terms"}
    return not any(w in text.lower() for w in bad)


def _extract_events_from_html(html: str) -> List[Dict[str, Any]]:
    """
    Very light-weight extractor (title + href). Replace with real parsing when needed.
    """
    items: List[Dict[str, Any]] = []
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{4,120})</a>', html, flags=re.I):
        href, title = m.groups()
        title = re.sub(r"\s+", " ", title).strip()
        if _looks_like_event_title(title):
            items.append(
                {
                    "source": "web",
                    "external_id": href,
                    "title": title,
                    "category": "Event",
                    "start_time": None,
                    "city": None,
                    "country": None,
                    "venue_name": None,
                    "min_price": None,
                    "currency": None,
                    "url": href,
                }
            )
    return items


def crawl_sites(
    *,
    client: HttpClient,
    city: str,
    country: str,
    allow_domains: Optional[Iterable[str]] = None,
    keyword: Optional[str] = None,
    limit_per_site: int = 25,
) -> List[Dict[str, Any]]:
    """
    Extremely simple HTML fetcher with retry/timeout protection.
    Use allow_domains to whitelist sources; otherwise DEFAULT_SITES.
    """
    domains = list(allow_domains or DEFAULT_SITES)
    all_items: List[Dict[str, Any]] = []

    for domain in domains:
        url = f"https://{domain}"
        try:
            resp = client.get(url, timeout=None)  # uses default timeout
            if resp.status_code >= 400:
                logger.info("Skip %s (HTTP %s)", url, resp.status_code)
                continue

            html = resp.text or ""
            items = _extract_events_from_html(html)
            if keyword:
                kw = keyword.lower()
                items = [it for it in items if kw in (it["title"] or "").lower()]

            # annotate location (best-effort)
            for it in items:
                it["city"] = it.get("city") or city
                it["country"] = it.get("country") or country

            if items:
                all_items.extend(items[:limit_per_site])

        except requests.HTTPError as e:
            logger.info("Web discovery HTTP error for %s: %s", url, e)
        except Exception as e:
            logger.info("Web discovery error for %s: %s", url, e)

    return all_items
