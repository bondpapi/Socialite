from __future__ import annotations

from typing import Any, Dict, List, Optional

DEFAULT_PROFILE: Dict[str, Any] = {
    "user_id": "demo-user",
    "username": "demo",
    "city": "",
    "country": "LT",
    "days_ahead": 120,
    "start_in_days": 0,
    "keywords": None,
    "passions": [],
}


def coerce_country(value: Any) -> str:
    """Normalize country-like values into ISO-2 uppercase."""
    if value is None:
        return "LT"

    if isinstance(value, str):
        v = value.strip().upper()
        return v[:2] if v else "LT"

    if isinstance(value, dict):
        for key in ("code", "alpha2", "alpha_2", "countryCode"):
            v = value.get(key)
            if v:
                return str(v).strip().upper()[:2] or "LT"
        name = value.get("name")
        if name:
            return str(name).strip().upper()[:2] or "LT"

    return "LT"


def normalize_profile(data: Optional[Dict[str, Any]] = None, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Single canonical profile normalizer used across the API and UI."""
    raw = dict(data or {})
    profile = {**DEFAULT_PROFILE, **raw}

    if user_id:
        profile["user_id"] = user_id

    profile["user_id"] = str(profile.get("user_id") or "demo-user").strip()
    profile["username"] = str(profile.get("username") or "demo").strip()
    profile["city"] = str(profile.get("city") or "").strip()
    profile["country"] = coerce_country(profile.get("country"))

    try:
        profile["days_ahead"] = int(profile.get("days_ahead") or 120)
    except Exception:
        profile["days_ahead"] = 120

    try:
        profile["start_in_days"] = int(profile.get("start_in_days") or 0)
    except Exception:
        profile["start_in_days"] = 0

    keywords = profile.get("keywords")
    profile["keywords"] = str(keywords).strip() if keywords else None

    passions = profile.get("passions") or []
    if isinstance(passions, str):
        passions = [p.strip() for p in passions.split(",") if p.strip()]
    elif not isinstance(passions, list):
        passions = []

    profile["passions"] = [str(p).strip() for p in passions if str(p).strip()]
    return profile


def build_search_params(profile: Dict[str, Any], *, include_mock: bool, limit: int = 20) -> Dict[str, Any]:
    normalized = normalize_profile(profile)
    city = (normalized.get("city") or "").strip()
    country = coerce_country(normalized.get("country"))

    if not city or not country:
        return {}

    params: Dict[str, Any] = {
        "city": city,
        "country": country,
        "days_ahead": int(normalized.get("days_ahead") or 90),
        "start_in_days": int(normalized.get("start_in_days") or 0),
        "include_mock": bool(include_mock),
        "limit": int(limit),
    }

    q = (normalized.get("keywords") or "").strip()
    if q:
        params["query"] = q

    return params
