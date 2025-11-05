# providers/ticketmaster.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from services import http
from providers.base import build_event, to_iso_z

KEY = "ticketmaster"
NAME = "Ticketmaster"
TM_URL = "https://app.ticketmaster.com/discovery/v2/events.json"

def _iso_window(start: datetime, end: datetime) -> Tuple[str, str]:
    return to_iso_z(start), to_iso_z(end)

def _parse_tm_item(it: Dict[str, Any]) -> Dict[str, Any]:
    title = it.get("name")
    url = it.get("url")
    description = it.get("info") or it.get("pleaseNote") or None

    # start time
    start_iso = None
    try:
        dt = ((it.get("dates") or {}).get("start") or {}).get("dateTime")
        if isinstance(dt, str):
            start_iso = dt if dt.endswith("Z") else dt.replace("+00:00", "Z")
    except Exception:
        pass

    # venue/city/country
    venue_name = None
    city = None
    country = None
    try:
        venues = (it.get("_embedded") or {}).get("venues", []) or []
        if venues:
            v0 = venues[0]
            venue_name = v0.get("name") or None
            city = (v0.get("city") or {}).get("name") or None
            country = (v0.get("country") or {}).get("countryCode") or None
    except Exception:
        pass

    # category
    category = None
    try:
        cls = (it.get("classifications") or [])[0]
        seg = (cls.get("segment") or {}).get("name")
        cat = (cls.get("genre") or {}).get("name") or seg
        category = cat
    except Exception:
        pass

    # image
    image_url = None
    try:
        imgs = it.get("images") or []
        if imgs:
            # pick the first (TM usually has many sizes)
            image_url = imgs[0].get("url")
    except Exception:
        pass

    # price
    currency, min_price = None, None
    try:
        pr = (it.get("priceRanges") or [])
        if pr:
            currency = pr[0].get("currency")
            min_price = pr[0].get("min")
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
        description=description,
        image_url=image_url,
        currency=currency,
        min_price=min_price,
        external_id=str(it.get("id") or ""),
        source=KEY,
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
            return []

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
            for it in ((data.get("_embedded") or {}).get("events") or []):
                items.append(_parse_tm_item(it))

        if not items:
            params.pop("city", None)
            resp2 = http.get(TM_URL, params=params, timeout=12)
            if resp2.status_code == 200:
                data2 = resp2.json() or {}
                for it in ((data2.get("_embedded") or {}).get("events") or []):
                    items.append(_parse_tm_item(it))

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
        api_key = getattr(settings, "ticketmaster_api_key", None) or getattr(settings, "TICKETMASTER_API_KEY", None)
    except Exception:
        api_key = None

    now = datetime.now(timezone.utc)
    start = (start or now.replace(hour=0, minute=0, second=0, microsecond=0))
    end = (end or (now + timedelta(days=90)).replace(hour=23, minute=59, second=59, microsecond=0))

    provider = TicketmasterProvider(api_key)
    return provider.search(city=city, country=country, start=start, end=end, query=query)
