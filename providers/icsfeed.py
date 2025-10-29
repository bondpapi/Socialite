from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from providers.base import build_event, to_iso_z
from services import http

KEY = "ics"
NAME = "ICS Feeds"

class ICSProvider:
    name = KEY

    def __init__(self, urls: List[str] | None) -> None:
        self.urls = urls or []

    @staticmethod
    def _parse_ics(text: str) -> List[Dict[str, Any]]:
        # Minimal iCalendar parser (BEGIN:VEVENT … END:VEVENT)
        out: List[Dict[str, Any]] = []
        lines = [ln.strip() for ln in text.splitlines()]
        i = 0
        while i < len(lines):
            if lines[i] == "BEGIN:VEVENT":
                props: Dict[str, str] = {}
                i += 1
                while i < len(lines) and lines[i] != "END:VEVENT":
                    ln = lines[i]
                    if ":" in ln:
                        k, v = ln.split(":", 1)
                        props[k.upper()] = v.strip()
                    i += 1
                # Build
                title = props.get("SUMMARY") or None
                url = props.get("URL") or None
                venue = props.get("LOCATION") or None
                # DTSTART can be in multiple forms; handle UTC basic forms
                dt_iso = None
                raw = props.get("DTSTART") or props.get("DTSTART;VALUE=DATE-TIME") or None
                if raw:
                    # Support YYYYMMDDTHHMMSSZ or YYYYMMDD
                    try:
                        if raw.endswith("Z"):
                            # 20250131T190000Z
                            dt = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                            dt_iso = to_iso_z(dt)
                        elif "T" in raw:
                            dt = datetime.strptime(raw, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
                            dt_iso = to_iso_z(dt)
                        else:
                            # All-day date
                            dt = datetime.strptime(raw, "%Y%m%d").replace(tzinfo=timezone.utc)
                            dt_iso = to_iso_z(dt)
                    except Exception:
                        dt_iso = None

                out.append(build_event(
                    title=title,
                    start_time=dt_iso,
                    city=None,
                    country=None,
                    url=url,
                    venue_name=venue,
                    category=None,
                    currency=None,
                    min_price=None,
                ))
            i += 1
        return out

    async def search(
        self,
        *,
        city: str,
        country: str,
        start: datetime,
        end: datetime,
        query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for url in self.urls:
            r = http.get(url, timeout=12)
            if r.status_code == 200 and "BEGIN:VCALENDAR" in r.text:
                parsed = self._parse_ics(r.text)
                # Optional: filter by keyword or date window
                for e in parsed:
                    ok = True
                    if query and e.get("title"):
                        ok = query.lower() in e["title"].lower()
                    if ok:
                        items.append(e)
        return items


def search(*, city: str, country: str, days_ahead: int = 60, start_in_days: int = 0, query: str | None = None):
    from datetime import datetime, timedelta, timezone
    urls = settings.ics_urls or []
    if not urls:
        return []
    start = (datetime.now(timezone.utc) + timedelta(days=start_in_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = (datetime.now(timezone.utc) + timedelta(days=start_in_days + days_ahead)).replace(hour=23, minute=59, second=59, microsecond=0)
    return ICSProvider(urls).collect(city=city, country=country, start=start, end=end, query=query)  # use your method names
