import httpx
from providers.base import EventRecord
from config import settings

SG_BASE = "https://api.seatgeek.com/2/events"

class SeatGeekProvider:
    name = "seatgeek"

    def __init__(self, client_id: str, client_secret: str | None = None):
        self.client_id = client_id
        self.client_secret = client_secret

    async def search(self, *, city: str, country: str, start=None, end=None, query=None):
        params = {"client_id": self.client_id}
        if self.client_secret:
            params["client_secret"] = self.client_secret
        if query:
            params["q"] = query
        if city:
            params["venue.city"] = city
        if country:
            params["venue.country"] = country

        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(SG_BASE, params=params)
            r.raise_for_status()
            data = r.json()

        results = []
        for e in data.get("events", []):
            v = e.get("venue", {}) or {}
            results.append(EventRecord(
                source=self.name,
                external_id=str(e.get("id")),
                title=e.get("short_title") or e.get("title") or "Event",
                category=(e.get("type") or "unknown"),
                start_time=e.get("datetime_local"),
                city=v.get("city") or city,
                country=v.get("country") or country,
                venue_name=v.get("name"),
                min_price=(e.get("stats") or {}).get("lowest_price"),
                currency="EUR",
                url=e.get("url"),
            ))
        return results
   
async def search(*, city: str, country: str, days_ahead: int = 60, start_in_days: int = 0, query: str | None = None):
    if not settings.seatgeek_client_id:
        return []
    provider = SeatGeekProvider(settings.seatgeek_client_id, settings.seatgeek_client_secret)
    return await provider.search(city=city, country=country, start=None, end=None, query=query)
    
