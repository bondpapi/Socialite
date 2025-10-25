from __future__ import annotations
from typing import Any, Dict, List, Optional

import re
import requests
from bs4 import BeautifulSoup

KEY = "kakava"
NAME = "Kakava"
BASE = "https://kakava.lt"  #

def _normalize(item: Dict[str, Any], *, city: str, country: str) -> Dict[str, Any]:
    return {
        "source": KEY,
        "external_id": item.get("external_id"),
        "title": item.get("title"),
        "category": item.get("category", "Event"),
        "start_time": item.get("start_time"),  # ISO8601 or None
        "city": item.get("city") or city,
        "country": item.get("country") or country,
        "venue_name": item.get("venue_name"),
        "min_price": item.get("min_price"),
        "currency": item.get("currency"),
        "url": item.get("url"),
    }

def _looks_like_event_title(text: str) -> bool:
    if not text:
        return False
    bad = {"cookies", "privacy", "login", "terms"}
    t = text.lower().strip()
    return len(t) >= 4 and not any(b in t for b in bad)

def search(
    *,
    city: str,
    country: str,
    days_ahead: int = 60,
    start_in_days: int = 0,
    query: Optional[str] = None,
) -> List[Dict[str, Any]]:
   
    items: List[Dict[str, Any]] = []

    try:
        # Fetch the front page (or replace with their events listing URL)
        r = requests.get(BASE, timeout=12)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")

        # Heuristic: collect anchors that look like event cards
        for a in soup.find_all("a", href=True):
            title = (a.get_text() or "").strip()
            href = a["href"]
            if not href.startswith("http"):
                href = BASE.rstrip("/") + "/" + href.lstrip("/")

            if not _looks_like_event_title(title):
                continue

            rec = {
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
            items.append(rec)

    except Exception as e:
        raise RuntimeError(f"{KEY} fetch failed: {e!r}")

    # Optional keyword filter
    if query:
        q = query.lower()
        items = [it for it in items if q in (it["title"] or "").lower()]

    return [_normalize(it, city=city, country=country) for it in items]
