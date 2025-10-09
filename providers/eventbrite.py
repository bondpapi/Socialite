from __future__ import annotations
import httpx
from datetime import datetime, timezone
from .base import EventRecord

EB_BASE = "https://www.eventbriteapi.com/v3"

CITY_COORDS = {
    ("tallinn","ee"): (59.437, 24.7536),
    ("riga","lv"): (56.9496, 24.1052),
    ("vilnius","lt"): (54.6872, 25.2797),
    ("berlin","de"): (52.52, 13.405),
}

def _to_iso_z(dt: datetime | None) -> str | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def _parse(dt_s: str | None) -> datetime | None:
    if not dt_s:
        return None
    return datetime.fromisoformat(dt_s.replace("Z", "+00:00"))

class EventbriteProvider:
    name = "eventbrite"

    def __init__(self, token: str, within_km: int = 75):
        self.token = token
        self.within_km = within_km

    async def search(self, *, city: str, country: str, start=None, end=None, query=None):
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

        # Keep params minimal; some regions/tokens 404 on extra fields
        base = {"sort_by": "date"}
        s = _to_iso_z(start); e = _to_iso_z(end)
        if s: base["start_date.range_start"] = s
        if e: base["start_date.range_end"] = e
        if query: base["q"] = query

        # Try address form first (city only)
        params = base | {"location.address": city, "location.within": f"{self.within_km}km"}

        async with httpx.AsyncClient(timeout=25) as client:
            try:
                r = await client.get(f"{EB_BASE}/events/search/", headers=headers, params=params)
                r.raise_for_status()
                data = r.json()
            except httpx.HTTPStatusError:
                # Fallback: lat/lon (more reliable)
                key = (city.lower(), country.lower())
                if key not in CITY_COORDS:
                    raise
                lat, lon = CITY_COORDS[key]
                params = base | {
                    "location.latitude": str(lat),
                    "location.longitude": str(lon),
                    "location.within": f"{self.within_km}km",
                }
                r = await client.get(f"{EB_BASE}/events/search/", headers=headers, params=params)
                r.raise_for_status()
                data = r.json()

        results = []
        for ev in data.get("events", []) or []:
            venue = ev.get("venue") or {}
            addr = venue.get("address") or {}
            title = (ev.get("name") or {}).get("text") or ev.get("name") or "Event"
            currency = ev.get("currency") or "EUR"
            is_free = bool(ev.get("is_free"))
            results.append(EventRecord(
                source=self.name,
                external_id=str(ev.get("id")),
                title=title,
                category="unknown",
                start_time=_parse((ev.get("start") or {}).get("utc")),
                city=addr.get("city") or city,
                country=addr.get("country") or country,
                venue_name=venue.get("name"),
                min_price=0.0 if is_free else None,
                currency=currency,
                url=ev.get("url"),
            ))
        return results
