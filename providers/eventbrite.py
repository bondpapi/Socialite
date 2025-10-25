from __future__ import annotations
from typing import Any, Dict, List, Optional
import logging
from datetime import datetime, timedelta, timezone
import requests
from utils.http_client import HttpClient

logger = logging.getLogger(__name__)

BASE_URL = "https://www.eventbriteapi.com/v3"


def _iso(dt: datetime) -> str:
    # Eventbrite expects UTC ISO with 'Z'
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def search(
    *,
    client: HttpClient,
    token: Optional[str],
    city: str,
    country: str,
    start_in_days: int,
    days_ahead: int,
    keyword: Optional[str] = None,
    radius_km: int = 75,
) -> List[Dict[str, Any]]:
    """
    Returns a normalized list of events from Eventbrite.
    Gracefully handles 404 and non-OK by returning [] and logging.
    """
    if not token:
        logger.debug("Eventbrite token not configured; skipping.")
        return []

    start = datetime.now(timezone.utc) + timedelta(days=start_in_days)
    end = start + timedelta(days=days_ahead)

    params: Dict[str, Any] = {
        "sort_by": "date",
        "location.address": city,
        "location.within": f"{radius_km}km",
        "start_date.range_start": _iso(start),
        "start_date.range_end": _iso(end),
        "expand": "venue",
        "page_size": 50,
    }
    if keyword:
        params["q"] = keyword

    headers = {"Authorization": f"Bearer {token}"}

    try:
        data = client.get_json(f"{BASE_URL}/events/search/", params=params, headers=headers, default={})
    except requests.HTTPError as e:
        logger.warning("Eventbrite search failed: %s", e)
        return []
    except Exception as e:
        logger.warning("Eventbrite unexpected error: %s", e)
        return []

    # Normalize
    items: List[Dict[str, Any]] = []
    events = (data or {}).get("events", []) if isinstance(data, dict) else []
    for ev in events:
        name = ((ev.get("name") or {}).get("text")) or "Untitled"
        start_time = ((ev.get("start") or {}).get("utc")) or None
        url = ev.get("url")
        venue = (ev.get("venue") or {}).get("name")

        items.append(
            {
                "source": "eventbrite",
                "external_id": ev.get("id"),
                "title": name,
                "category": "Event",
                "start_time": start_time,
                "city": city,
                "country": country,
                "venue_name": venue,
                "min_price": None,
                "currency": None,
                "url": url,
            }
        )
    return items
