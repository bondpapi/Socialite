from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..services import http
from .base import build_event
from ..config import settings

KEY = "ticketmaster"
NAME = "Ticketmaster"

TM_URL = "https://app.ticketmaster.com/discovery/v2/events.json"


def _iso_window(start: datetime, end: datetime) -> Tuple[str, str]:
    # TM expects Z-suffixed ISO
    return start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_tm_item(it: Dict[str, Any]) -> Dict[str, Any]:
    title = it.get("name")
    url = it.get("url")

    start_iso = None
    dates = it.get("dates") or {}
    start_dt = dates.get("start") or {}
    dt = start_dt.get("dateTime") or start_dt.get("dateTBD") or None
    if isinstance(dt, str):
        try:
            start_iso = dt if dt.endswith("Z") else dt.replace("+00:00", "Z")
        except Exception:
            start_iso = dt

    venue_name = None
    city = None
    country = None
    try:
        venues = (it.get("_embedded") or {}).get("venues", [])
        if venues:
            v0 = venues[0]
            venue_name = v0.get("name") or None
            city = (v0.get("city") or {}).get("name") or None
            country = (v0.get("country") or {}).get("countryCode") or None
    except Exception:
        pass

    category = None
    try:
        if it.get("classifications"):
            cls = it["classifications"][0] or {}
            seg = (cls.get("segment") or {}).get("name")
            category = (cls.get("genre") or {}).get("name") or seg
    except Exception:
        pass

    currency = None
    min_price = None
    try:
        price_ranges = it.get("priceRanges") or []
        if price_ranges:
            pr = price_ranges[0]
            currency = pr.get("currency")
            min_price = pr.get("min")
    except Exception:
        pass

    return build_event(
        title=title,
        start_time=start_iso,
        city=city,
        country=country,
        url=url,
        venue_name=venue_name,
        category=category,
        currency=currency,
        min_price=min_price,
    )


class TicketmasterProvider:
    name = KEY

    def __init__(self, api_key: Optional[str]) -> None:
        self.api_key = api_key

    async def search(
        self,
        *,
        city: str,
        country: str,
        start: datetime,
        end: datetime,
        query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("ticketmaster_api_key not configured")

        start_iso, end_iso = _iso_window(start, end)

        params = {
            "apikey": self.api_key,
            "countryCode": country,
            "city": city,
            "startDateTime": start_iso,
            "endDateTime": end_iso,
            "size": 200,
            "sort": "date,asc",
        }
        if query:
            params["keyword"] = query

        items: List[Dict[str, Any]] = []

        resp = http.get(TM_URL, params=params, timeout=12)
        if resp.status_code == 200:
            data = resp.json() or {}
            events = (data.get("_embedded") or {}).get("events") or []
            for it in events:
                items.append(_parse_tm_item(it))

        # If no results for city, broaden search by removing city constraint
        if not items:
            params.pop("city", None)
            resp2 = http.get(TM_URL, params=params, timeout=12)
            if resp2.status_code == 200:
                data2 = resp2.json() or {}
                events2 = (data2.get("_embedded") or {}).get("events") or []
                for it in events2:
                    items.append(_parse_tm_item(it))

        return items


async def search(
    *,
    city: str,
    country: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    api_key = getattr(settings, "ticketmaster_api_key", None)

    if start is None or end is None:
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = (now + timedelta(days=90)).replace(hour=23, minute=59, second=59, microsecond=0)

    provider = TicketmasterProvider(api_key)
    return await provider.search(city=city, country=country, start=start, end=end, query=query)
