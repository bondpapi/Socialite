from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..common import DEFAULT_PROFILE, normalize_profile

router = APIRouter(prefix="/profile", tags=["profile"])

_storage = None
try:
    from ..services import storage as _storage
except Exception:
    try:
        from services import storage as _storage
    except Exception:
        pass


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


@router.get("/{user_id}")
def get_profile(user_id: str) -> Dict[str, Any]:
    default_profile = {
        "user_id": user_id,
        "username": "demo",
        "city": "",
        "country": "LT",
        "days_ahead": 120,
        "start_in_days": 0,
        "keywords": None,
        "passions": [],
    }

    if _storage and hasattr(_storage, "get_profile"):
        try:
            prof = _storage.get_profile(user_id)

            if not prof:
                prof = default_profile
            else:
                prof = {**default_profile, **prof}

            return {"ok": True, "profile": prof}

        except Exception as e:
            return {
                "ok": False,
                "profile": default_profile,
                "error": str(e),
            }

    return {
        "ok": True,
        "profile": default_profile,
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
