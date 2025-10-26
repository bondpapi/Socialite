from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import re

ISO_Z_FMT = "%Y-%m-%dT%H:%M:%SZ"

def to_iso_z(dt: datetime | None) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime(ISO_Z_FMT)

_ws_re = re.compile(r"\s+")

def _clean(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return _ws_re.sub(" ", s).strip()

def build_event(
    *,
    title: Optional[str],
    start_time: Optional[str],
    city: Optional[str],
    country: Optional[str],
    url: Optional[str],
    venue_name: Optional[str],
    category: Optional[str] = None,
    currency: Optional[str] = None,
    min_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Return a normalized event object (aggregator sets `source`)."""
    return {
        "title": _clean(title),
        "start_time": start_time,
        "city": _clean(city),
        "country": (country or None),
        "url": url or None,
        "venue_name": _clean(venue_name),
        "category": (category or None),
        "currency": (currency or None),
        "min_price": float(min_price) if min_price is not None else None,
    }
