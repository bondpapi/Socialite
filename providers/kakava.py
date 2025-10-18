"""
kakava.lt provider (skeleton). 
"""
from __future__ import annotations
from typing import Dict, List, Any, Tuple
from bs4 import BeautifulSoup  # add to requirements.txt
from ..services.http import get

BASE = "https://kakava.lt"  # TODO: verify base and endpoints


def _normalize(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": "kakava",
        "external_id": item.get("external_id"),
        "title": item.get("title"),
        "category": item.get("category", "Event"),
        "start_time": item.get("start_time"),
        "city": item.get("city"),
        "country": item.get("country"),
        "venue_name": item.get("venue"),
        "min_price": item.get("min_price"),
        "currency": item.get("currency"),
        "url": item.get("url"),
    }


def search(city: str, country: str, start_iso: str, end_iso: str, query: str | None) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Returns (items, errors)
    Implement real query → parse logic here.
    """
    items: List[Dict[str, Any]] = []
    errors: List[str] = []

    try:
        # Example HTML fetch — replace with real search URL/params
        # url = f"{BASE}/search?city={city}&q={query or ''}"
        # r = get(url, timeout=12)
        # if r.status_code != 200:
        #     errors.append(f"kakava.lt HTTP {r.status_code}")
        #     return items, errors
        # soup = BeautifulSoup(r.text, "html.parser")
        # ... parse soup ...
        pass
    except Exception as e:
        errors.append(f"kakava.lt error: {e!r}")

    return [ _normalize(i) for i in items ], errors
