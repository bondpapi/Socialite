from __future__ import annotations
from typing import Any, Dict, List, Optional
import re

import requests
from bs4 import BeautifulSoup

KEY = "kakava"
NAME = "Kakava"
BASE = "https://kakava.lt/en"


def _full_url(href: str) -> str:
    if not href:
        return BASE
    if href.startswith("http"):
        return href
    return BASE.rstrip("/") + "/" + href.lstrip("/")


def _looks_like_event_title(text: str) -> bool:
    if not text:
        return False
    bad = {"cookies", "privacy", "login", "terms", "cart", "gift", "discounts"}
    t = text.lower().strip()
    return len(t) >= 4 and not any(b in t for b in bad)


def _normalize(item: Dict[str, Any], *, city: str, country: str) -> Dict[str, Any]:
    return {
        "source": KEY,
        "external_id": item.get("external_id"),
        "title": item.get("title"),
        "category": item.get("category", "Event"),
        "start_time": item.get("start_time"),  # ISO-8601 string or None
        "city": item.get("city") or city,
        "country": item.get("country") or country,
        "venue_name": item.get("venue_name"),
        "min_price": item.get("min_price"),
        "currency": item.get("currency"),
        "url": item.get("url"),
    }


def _scrape_cards(html: str, *, city: str, country: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Strategy:
    # - Find anchor tags inside typical "card" containers.
    # - Prefer anchors whose href looks like an event/product page (heuristic).
    anchors = soup.find_all("a", href=True)

    for a in anchors:
        title = (a.get_text(separator=" ", strip=True) or "").strip()
        href = a["href"].strip()

        # Heuristics: many event/product URLs contain something other than top-level nav;
        # also skip obvious nav/filter links.
        if not _looks_like_event_title(title):
            continue
        if re.search(r"(login|register|cart|profile|gift|discount|cookies|privacy)", href, flags=re.I):
            continue

        url = _full_url(href)

        items.append(
            {
                "external_id": url,
                "title": title,
                "category": "Event",
                "start_time": None,  # Could be parsed by going into detail pages later
                "city": city,
                "country": country,
                "venue_name": None,
                "min_price": None,
                "currency": None,
                "url": url,
            }
        )

    # Deduplicate by URL
    seen = set()
    out: List[Dict[str, Any]] = []
    for it in items:
        u = it["url"]
        if u in seen:
            continue
        seen.add(u)
        out.append(it)
    return out


def search(
    *,
    city: str,
    country: str,
    days_ahead: int = 60,
    start_in_days: int = 0,
    query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Minimal Kakava provider. Fetches the homepage (EN) and extracts event-like links.
    Later you can swap BASE to a listing URL or add a second request to detail pages
    to parse dates/venues/prices.
    """
    # Prefer English to reduce non-event text noise
    url = BASE + "/en" if BASE.endswith("/") else BASE + "/en"

    r = requests.get(url, timeout=12)
    r.raise_for_status()

    items = _scrape_cards(r.text, city=city, country=country)

    if query:
        q = query.lower()
        items = [it for it in items if q in (it["title"] or "").lower()]

    return [_normalize(it, city=city, country=country) for it in items]
