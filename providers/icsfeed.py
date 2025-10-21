from __future__ import annotations
import httpx
from datetime import datetime, timezone, date
from icalendar import Calendar
from base import EventRecord

class ICSFeedProvider:
    name = "ics"

    def __init__(self, urls: list[str]):
        self.urls = urls

    def _as_dt(self, v):
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if isinstance(v, date):
            return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
        return None

    async def search(self, *, city: str, country: str, start=None, end=None, query=None):
        results = []
        async with httpx.AsyncClient(timeout=25) as client:
            for url in self.urls:
                try:
                    r = await client.get(url)
                    r.raise_for_status()
                    cal = Calendar.from_ical(r.text)
                except Exception as e:
                    print(f"[ICS] fetch error {url}: {e}")
                    continue

                for comp in cal.walk("vevent"):
                    summary = str(comp.get("summary") or "Event")
                    dtstart = comp.get("dtstart")
                    dt = self._as_dt(dtstart.dt) if dtstart else None
                    if start and dt and dt < start:
                        continue
                    if end and dt and dt > end:
                        continue
                    loc = comp.get("location")
                    url_field = comp.get("url")
                    if query:
                        q = query.lower()
                        if q not in summary.lower() and (not loc or q not in str(loc).lower()):
                            continue

                    results.append(EventRecord(
                        source=self.name,
                        external_id=str(comp.get("uid") or f"{url}:{summary}:{dt}"),
                        title=summary,
                        category="unknown",
                        start_time=dt,
                        city=city,           # best-effort
                        country=country,
                        venue_name=str(loc) if loc else None,
                        min_price=None,
                        currency="EUR",
                        url=str(url_field) if url_field else None,
                    ))
        return results
