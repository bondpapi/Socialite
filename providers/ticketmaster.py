from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from providers.base import build_event, to_iso_z
from services import http

KEY = "ticketmaster"
NAME = "Ticketmaster"
TM_URL = "https://app.ticketmaster.com/discovery/v2/events.json"


# --------- helpers ---------


def _iso_window(start: datetime, end: datetime) -> Tuple[str, str]:
    return to_iso_z(start), to_iso_z(end)


def _first(x):
    return x[0] if isinstance(x, list) and x else None


def _country_iso(venue: Dict[str, Any], fallback: str = "") -> str:
    c = (venue or {}).get("country") or {}
    code = (c.get("countryCode") or "").strip().upper()
    if len(code) == 2:
        return code
    name = (c.get("name") or "").strip()
    if len(name) >= 2:
        return name[:2].upper()
    return (fallback or "").strip().upper()[:2]


def _parse_tm_item(it: Dict[str, Any], country_default: str) -> Dict[str, Any]:
    title = it.get("name")
    url = it.get("url")

    # start time
    start_iso = None
    try:
        dt = ((it.get("dates") or {}).get("start") or {}).get("dateTime")
        if isinstance(dt, str):
            # normalize to Z
            if dt.endswith("Z"):
                start_iso = dt
            else:
                start_iso = dt.replace("+00:00", "Z")
    except Exception:
        pass

    # venue/city/country
    venue = _first(((it.get("_embedded") or {}).get("venues")) or [])
    venue_name = (
        venue.get("name") if isinstance(venue, dict) else None
    )
    city = (
        (venue.get("city") or {}).get("name")
        if isinstance(venue, dict) else None
    )
    country = _country_iso(venue or {}, fallback=country_default)

    # category
    category = None
    try:
        cls = _first(it.get("classifications") or [])
        if isinstance(cls, dict):
            seg = (cls.get("segment") or {}).get("name")
            gen = (cls.get("genre") or {}).get("name")
            category = gen or seg
    except Exception:
        pass

    # image
    image_url = None
    img = _first(it.get("images") or [])
    if isinstance(img, dict):
        image_url = img.get("url")

    # price
    currency, min_price = None, None
    pr = _first(it.get("priceRanges") or [])
    if isinstance(pr, dict):
        currency = pr.get("currency")
        try:
            if pr.get("min") is not None:
                min_price = float(pr["min"])
        except Exception:
            pass

    # description (avoid boilerplate "Event")
    description = it.get("info") or it.get("pleaseNote") or None
    if (description and isinstance(description, str) and
            description.strip().lower() == "event"):
        description = None

    return build_event(
        title=title,
        start_time=start_iso,
        city=city,
        country=country or country_default,
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


# --------- provider (SYNC) ---------


class TicketmasterProvider:
    name = KEY

    def __init__(self, api_key: Optional[str]) -> None:
        self.api_key = api_key

    def search(
        self,
        *,
        city: str,
        country: str,
        start: datetime,
        end: datetime,
        query: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []

        start_iso, end_iso = _iso_window(start, end)
        cc = (country or "").strip().upper()[:2]

        params = {
            "apikey": self.api_key,
            "startDateTime": start_iso,
            "endDateTime": end_iso,
            "countryCode": cc,
            "size": max(1, min(limit, 200)),
            "page": max(0, offset // max(1, min(limit, 200))),
            "sort": "date,asc",
            "locale": "*",
        }
        if city:
            params["city"] = city
        if query:
            params["keyword"] = query

        items: List[Dict[str, Any]] = []

        try:
            resp = http.get(TM_URL, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json() or {}
                for it in ((data.get("_embedded") or {}).get("events") or []):
                    items.append(_parse_tm_item(it, country_default=cc))
        except Exception:
            pass

        # fallback: drop city if nothing found
        if not items and params.get("city"):
            params.pop("city", None)
            try:
                resp2 = http.get(TM_URL, params=params, timeout=15)
                if resp2.status_code == 200:
                    data2 = resp2.json() or {}
                    events = (
                        (data2.get("_embedded") or {}).get("events") or []
                    )
                    for it in events:
                        items.append(
                            _parse_tm_item(it, country_default=cc)
                        )
            except Exception:
                pass

        return items


# --------- module entry (SYNC) ---------


def search(
    *,
    city: str,
    country: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Synchronous entrypoint expected by your aggregator.
    """
    # pull key from env or config
    api_key = os.getenv("TICKETMASTER_API_KEY")
    if not api_key:
        try:
            from config import settings
            api_key = (
                getattr(settings, "ticketmaster_api_key", None) or
                getattr(settings, "TICKETMASTER_API_KEY", None)
            )
        except Exception:
            api_key = None

    # default window if not provided
    if start is None or end is None:
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = (now + timedelta(days=90)).replace(
            hour=23, minute=59, second=59, microsecond=0
        )

    provider = TicketmasterProvider(api_key)
    return provider.search(
        city=city,
        country=country,
        start=start,
        end=end,
        query=query,
        limit=limit,
        offset=offset,
    )
