from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/profile", tags=["profile"])

_storage = None
try:
    from services import storage as _storage
except Exception:
    pass


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


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_id: str = Field(default="demo-user")
    username: Optional[str] = "demo"
    city: Optional[str] = ""
    country: Optional[str] = "LT"
    days_ahead: Optional[int] = 120
    start_in_days: Optional[int] = 0
    keywords: Optional[str] = None
    passions: Optional[List[str]] = None


def normalize_profile(data: Optional[Dict[str, Any]], user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Normalize profile shape so FastHTML, Streamlit, and backend routes all
    receive the same predictable fields.
    """
    raw = dict(data or {})

    profile = {**DEFAULT_PROFILE, **raw}

    if user_id:
        profile["user_id"] = user_id

    profile["user_id"] = str(profile.get("user_id") or "demo-user").strip()
    profile["username"] = str(profile.get("username") or "demo").strip()
    profile["city"] = str(profile.get("city") or "").strip()

    country = profile.get("country") or "LT"
    if isinstance(country, dict):
        country = (
            country.get("code")
            or country.get("alpha2")
            or country.get("alpha_2")
            or country.get("countryCode")
            or country.get("name")
            or "LT"
        )
    profile["country"] = str(country or "LT").strip().upper()[:2]

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


@router.get("/{user_id}")
def get_profile(user_id: str) -> Dict[str, Any]:
    if _storage and hasattr(_storage, "get_profile"):
        try:
            prof = _storage.get_profile(user_id)
            return {"ok": True, "profile": normalize_profile(prof, user_id=user_id)}
        except Exception as e:
            return {
                "ok": False,
                "profile": normalize_profile({"user_id": user_id}, user_id=user_id),
                "error": str(e),
            }

    return {
        "ok": True,
        "profile": normalize_profile({"user_id": user_id}, user_id=user_id),
        "debug": {"storage": "not_configured"},
    }


@router.post("")
def upsert_profile(p: ProfileIn) -> Dict[str, Any]:
    """
    Preferred endpoint: POST /profile with JSON body including user_id.
    """
    data = normalize_profile(p.model_dump())

    if _storage and hasattr(_storage, "upsert_profile"):
        try:
            saved = _storage.upsert_profile(data)
            return {"ok": True, "profile": normalize_profile(saved, user_id=data["user_id"])}
        except Exception as e:
            return {"ok": False, "profile": data, "error": str(e)}

    return {
        "ok": True,
        "profile": data,
        "debug": {"storage": "not_configured"},
    }


@router.post("/{user_id}")
def upsert_profile_with_path(user_id: str, p: ProfileIn) -> Dict[str, Any]:
    """
    Compatibility endpoint: POST /profile/{user_id}
    """
    data = normalize_profile(p.model_dump(), user_id=user_id)

    if _storage and hasattr(_storage, "upsert_profile"):
        try:
            saved = _storage.upsert_profile(data)
            return {"ok": True, "profile": normalize_profile(saved, user_id=user_id)}
        except Exception as e:
            return {"ok": False, "profile": data, "error": str(e)}

    return {
        "ok": True,
        "profile": data,
        "debug": {
            "storage": "not_configured",
            "note": "handled via /profile/{user_id} compatibility route",
        },
    }