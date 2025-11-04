from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional
import logging
import re
import json
from pathlib import Path

from utils.http_client import HttpClient
from utils.cache import FileCache

logger = logging.getLogger(__name__)

DEFAULT_SITES = [
    "bilietai.lt",
    "piletilevi.ee",
    "bilesuserviss.lv",
    "tiketa.lt",
    "kakava.lt",
]
CACHE_NS = "web_discovery"

# Optional settings (safe defaults)
try:
    from config import settings  # type: ignore
    cache_root = Path(getattr(settings, "cache_dir", "."))
    cache_enabled = bool(getattr(settings, "cache_enabled", True))
    cache_ttl = float(getattr(settings, "web_cache_ttl_seconds", 3600.0))
except Exception:
    cache_root = Path(".")
    cache_enabled = True
    cache_ttl = 3600.0

cache = FileCache(cache_root, enabled=cache_enabled)

def _looks_like_event_title(text: str) -> bool:
    if not text:
        return False
    bad = {"cookies", "privacy", "login", "terms"}
    return not any(w in text.lower() for w in bad)

def _extract_events_from_html(html: str, *, city: str, country: str) -> List[Dict[str, Any]]:
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
                    "city": city,
                    "country": country,
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
    domains = list(allow_domains or DEFAULT_SITES)
    all_items: List[Dict[str, Any]] = []

    for domain in domains:
        url = f"https://{domain}"

        cache_key = json.dumps(
            {"domain": domain, "city": city, "country": country, "keyword": keyword, "limit": limit_per_site},
            sort_keys=True,
        )

        def _fetch_html() -> str:
            try:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.text or ""
            except Exception as e:
                logger.info("Web discovery error for %s: %s", url, e)
                return ""

        html = cache.get_or_set(
            CACHE_NS,
            cache_key,
            max_age=cache_ttl,
            producer=_fetch_html,
        )

        if not html:
            continue

        items = _extract_events_from_html(html, city=city, country=country)
        if keyword:
            kw = keyword.lower()
            items = [it for it in items if kw in (it["title"] or "").lower()]

        if items:
            all_items.extend(items[:limit_per_site])

    return all_items
