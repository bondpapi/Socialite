# providers/eventbrite.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from services import http
from providers.base import build_event, to_iso_z

KEY = "eventbrite"
NAME = "Eventbrite"
EB_URL = "https://www.eventbriteapi.com/v3/events/search/"

def _iso_window(start: datetime, end: datetime) -> Tuple[str, str]:
    return to_iso_z(start), to_iso_z(end)

def _parse_venue(venue: Dict[str, Any]) -> Dict[str, Optional[str]]:
    name = venue.get("name") or None
    address = venue.get("address") or {}
    city = address.get("city") or None
    country = address.get("country") or None
    return {"venue_name": name, "city": city, "country": country}

def _parse_event(e: Dict[str, Any], venue_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    title = (e.get("name") or {}).get("text") or e.get("name") or None
    url = e.get("url")
    description = (e.get("description") or {}).get("text") or None
    image_url = (e.get("logo") or {}).get("url") or None
    category = e.get("category_id") or None

    start_iso = None
    try:
        start_iso = (e.get("start") or {}).get("utc") or None
        if start_iso and not start_iso.endswith("Z"):
            start_iso = start_iso.replace("+00:00", "Z")
    except Exception:
        pass

    venue_name, city, country = None, None, None
    venue_id = e.get("venue_id")
    if venue_id and venue_id in venue_map:
        v = venue_map[venue_id]
        parsed = _parse_venue(v)
        venue_name = parsed["venue_name"]
        city = parsed["city"]
        country = parsed["country"]

    # Eventbrite ticket classes are on a different endpoint; keep price fields None here.
    return build_event(
        title=title,
        start_time=start_iso,
        city=city,
        country=country,
        url=url,
        venue_name=venue_name,
        category=category,
        description=description,
        image_url=image_url,
        currency=None,
        min_price=None,
        external_id=str(e.get("id") or ""),
        source=KEY,
    )

class EventbriteProvider:
    name = KEY
    def __init__(self, token: Optional[str]) -> None:
        self.token = token

    async def search(
        self,
        *,
        city: str,
        country: str,
        start: datetime,
        end: datetime,
        query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not self.token:
            return []

        start_iso, end_iso = _iso_window(start, end)
        headers = {"Authorization": f"Bearer {self.token}"}

        params: Dict[str, Any] = {
            "location.address": city,
            "location.within": "100km",
            "start_date.range_start": start_iso,
            "start_date.range_end": end_iso,
            "expand": "venue",
            "include_adult_events": "false",
            "sort_by": "date",
            "page_size": 200,
        }
        if query:
            params["q"] = query

        items: List[Dict[str, Any]] = []
        venue_map: Dict[str, Dict[str, Any]] = {}

        def collect(resp_json: Dict[str, Any]) -> None:
            nonlocal items, venue_map
            events = resp_json.get("events") or []
            for ev in events:
                ven = ev.get("venue")
                if isinstance(ven, dict) and ven.get("id"):
                    venue_map[ven["id"]] = ven
            for ev in events:
                items.append(_parse_event(ev, venue_map))

        resp = http.get(EB_URL, params=params, headers=headers, timeout=12)
        if resp.status_code == 200:
            collect(resp.json() or {})

        if not items:
            params.pop("location.address", None)
            params["location.within"] = "400km"
            resp2 = http.get(EB_URL, params=params, headers=headers, timeout=12)
            if resp2.status_code == 200:
                collect(resp2.json() or {})

        return items

def search(
    *,
    city: str,
    country: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    query: Optional[str] = None,
):
    try:
        from config import settings
        token = getattr(settings, "eventbrite_token", None) or getattr(settings, "EVENTBRITE_TOKEN", None)
    except Exception:
        token = None

    now = datetime.now(timezone.utc)
    start = (start or now.replace(hour=0, minute=0, second=0, microsecond=0))
    end = (end or (now + timedelta(days=90)).replace(hour=23, minute=59, second=59, microsecond=0))

    provider = EventbriteProvider(token)
    return provider.search(city=city, country=country, start=start, end=end, query=query)
