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
    venue_name: Optional[str] = None,
    category: Optional[str] = None,
    # New/enriched fields:
    description: Optional[str] = None,
    image_url: Optional[str] = None,
    currency: Optional[str] = None,
    min_price: Optional[float] = None,
    external_id: Optional[str] = None,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "id": None,
        "external_id": external_id,
        "source": source,     # upstream sets this (aggregator also sets default)
        "title": title or "",
        "category": category,
        "start_time": start_time,
        "city": city,
        "country": country,
        "venue_name": venue_name,
        "url": url,
        "description": (description or None),
        "image_url": (image_url or None),
        "currency": currency,
        "min_price": min_price,
    }
