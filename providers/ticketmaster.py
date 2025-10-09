# social_agent_ai/providers/ticketmaster.py
from __future__ import annotations
import httpx
from datetime import datetime, timezone
from .base import EventRecord

TM_BASE = "https://app.ticketmaster.com/discovery/v2"

def _to_tm_iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def _parse_dt(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    # TM returns e.g. "2025-10-05T18:30:00Z"
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))

class TicketmasterProvider:
    name = "ticketmaster"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(self, *, city: str, country: str,
                     start: datetime | None = None,
                     end: datetime | None = None,
                     query: str | None = None):
        params = {
            "apikey": self.api_key,
            "size": 100,
            "sort": "date,asc",
            "countryCode": country,   # ISO-2, e.g., LT, LV, EE, DE
            "city": city,
        }
        s = _to_tm_iso(start)
        e = _to_tm_iso(end)
        if s:
            params["startDateTime"] = s
        if e:
            params["endDateTime"] = e
        if query:
            params["keyword"] = query

        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.get(f"{TM_BASE}/events.json", params=params)
            r.raise_for_status()
            data = r.json()

        events = []
        for ev in (data.get("_embedded", {}) or {}).get("events", []) or []:
            venues = (ev.get("_embedded", {}) or {}).get("venues", []) or [{}]
            v = venues[0] or {}
            # min price if present
            pr = (ev.get("priceRanges") or [])
            min_price = None
            currency = None
            if pr:
                min_price = pr[0].get("min") or pr[0].get("max")
                currency = pr[0].get("currency")

            events.append(EventRecord(
                source=self.name,
                external_id=ev.get("id"),
                title=ev.get("name"),
                category=((ev.get("classifications") or [{}])[0].get("segment") or {}).get("name", "unknown"),
                start_time=_parse_dt((ev.get("dates") or {}).get("start", {}).get("dateTime")),
                city=(v.get("city") or {}).get("name") or city,
                country=(v.get("country") or {}).get("countryCode") or country,
                venue_name=v.get("name"),
                min_price=min_price,
                currency=currency or "EUR",
                url=ev.get("url"),
            ))
        return events
