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


# Normalization helpers

# Common names/aliases -> ISO-2
_COUNTRY_ALIASES = {
    # Baltics + regional
    "lt": "LT", "lithuania": "LT", "lietuva": "LT",
    "lv": "LV", "latvia": "LV", "latvija": "LV",
    "ee": "EE", "estonia": "EE", "eesti": "EE",
    "pl": "PL", "poland": "PL",
    "de": "DE", "germany": "DE", "deutschland": "DE",
    "se": "SE", "sweden": "SE",
    "fi": "FI", "finland": "FI",
    "no": "NO", "norway": "NO",
    "ru": "RU", "russia": "RU", "россия": "RU",
    "by": "BY", "belarus": "BY", "беларусь": "BY",
    # Add more as you encounter them
}

def _coerce_country(value: Any, default: Optional[str] = None) -> Optional[str]:
    """
    Convert arbitrary provider 'country' fields into an ISO-2 string.
    Accepts strings (code or name) and dicts (JSON-LD/address objects).
    """
    if value is None:
        return default

    # Dict from JSON-LD/APIs: try common keys
    if isinstance(value, dict):
        for k in ("countryCode", "addressCountry", "name", "code"):
            v = value.get(k)
            if v:
                return _coerce_country(v, default)
        return default

    # Strings
    if isinstance(value, str):
        s = value.strip()
        if len(s) == 2 and s.isalpha():
            return s.upper()
        alias = _COUNTRY_ALIASES.get(s.lower())
        if alias:
            return alias
        # Fallback: if string is longer, keep first 2 letters uppercased
        return s[:2].upper() if len(s) >= 2 else default

    return default


def _coerce_currency(value: Any) -> Optional[str]:
    """Uppercase 3-letter currency codes when possible."""
    if not value:
        return None
    if isinstance(value, str):
        v = value.strip().upper()
        return v[:3] if len(v) >= 3 else v or None
    return None


def _coerce_min_price(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        s = str(v).strip()
        if not s:
            return None
        return float(s)
    except Exception:
        return None


# --------------------------
# Public builder
# --------------------------

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
    """
    Standardizes provider outputs and guarantees schema-friendly types.
    Critically, 'country' is normalized to ISO-2 to satisfy Pydantic models.
    """
    return {
        "id": None,
        "external_id": external_id or None,
        "source": source or "web",
        "title": (title or "").strip(),
        "category": _clean(category),
        "start_time": start_time,                 # already ISO string if provided
        "city": _clean(city),
        "country": _coerce_country(country),      # <-- normalization fix
        "venue_name": _clean(venue_name),
        "url": url,
        "description": _clean(description) or None,
        "image_url": image_url or None,
        "currency": _coerce_currency(currency),
        "min_price": _coerce_min_price(min_price),
    }
