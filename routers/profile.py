from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/profile", tags=["profile"])

_storage = None
try:
    from services import storage as _storage
except Exception:
    pass


class ProfileIn(BaseModel):
    user_id: str
    username: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    passions: Optional[List[str]] = None


@router.get("/{user_id}")
def get_profile(user_id: str) -> Dict[str, Any]:
    if _storage and hasattr(_storage, "get_profile"):
        try:
            prof = _storage.get_profile(user_id)
            return {"ok": True, "profile": prof}
        except Exception as e:
            return {"ok": False, "profile": None, "error": str(e)}

    # graceful fallback
    return {
        "ok": True,
        "profile": {"user_id": user_id},
        "debug": {"storage": "not_configured"},
    }


@router.post("")
def upsert_profile(p: ProfileIn) -> Dict[str, Any]:
    """
    Preferred endpoint: POST /profile with JSON body including user_id.
    """
    data = p.model_dump()
    if _storage and hasattr(_storage, "upsert_profile"):
        try:
            saved = _storage.upsert_profile(data)
            return {"ok": True, "profile": saved}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return {
        "ok": True,
        "profile": data,
        "debug": {"storage": "not_configured"},
    }


@router.post("/{user_id}")
def upsert_profile_with_path(user_id: str, p: ProfileIn) -> Dict[str, Any]:
    """
    Compatibility endpoint: POST /profile/{user_id}

    Your Streamlit app is currently calling this URL, so we accept it and
    forward to the same storage logic, forcing user_id from the path.
    """
    data = p.model_dump()
    data["user_id"] = user_id  # trust the path ID

    if _storage and hasattr(_storage, "upsert_profile"):
        try:
            saved = _storage.upsert_profile(data)
            return {"ok": True, "profile": saved}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return {
        "ok": True,
        "profile": data,
        "debug": {
            "storage": "not_configured",
            "note": "handled via /profile/{user_id} compatibility route",
        },
    }
