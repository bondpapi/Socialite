from __future__ import annotations
from typing import Any, Dict, List, Optional
from pathlib import Path

from utils.cache import FileCache
from utils.http_client import HttpClient
from config import settings
from providers import web_discovery

KEY = "web"
NAME = "Web Discovery"

try:
    from config import settings
    cache_root = Path(getattr(settings, "cache_dir", "."))  # default to current dir
except Exception:
    cache_root = Path(".")

cache = FileCache(cache_root, enabled=True)

def search(
    *,
    city: str,
    country: str,
    days_ahead: int = 60,
    start_in_days: int = 0,
    query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    client = HttpClient(timeout=settings.http_timeout_seconds)

    items = web_discovery.crawl_sites(
        client=client,
        city=city,
        country=country,
        allow_domains=None, 
        keyword=query,
        limit_per_site=25,
    )

    # Conform to aggregator schema and fill blanks
    out: List[Dict[str, Any]] = []
    for it in items:
        it.setdefault("source", KEY)
        it.setdefault("category", "Event")
        it.setdefault("start_time", None)
        it.setdefault("venue_name", None)
        it.setdefault("min_price", None)
        it.setdefault("currency", None)
        it.setdefault("city", city)
        it.setdefault("country", country)
        out.append(it)

    return out
