# routers/profile.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

router = APIRouter(prefix="/profile", tags=["profile"])

_storage = None
try:
    from services import storage as _storage  # your storage service
except Exception:
    pass


class ProfileIn(BaseModel):
    user_id: str
    username: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    passions: Optional[List[str]] = None  # interests/tags


@router.get("/{user_id}")
def get_profile(user_id: str) -> Dict[str, Any]:
    if _storage and hasattr(_storage, "get_profile"):
        try:
            prof = _storage.get_profile(user_id)
            return {"ok": True, "profile": prof}
        except Exception as e:
            return {"ok": False, "profile": None, "error": str(e)}

    # graceful fallback
    return {"ok": True, "profile": {"user_id": user_id}, "debug": {"storage": "not_configured"}}


@router.post("")
def upsert_profile(p: ProfileIn) -> Dict[str, Any]:
    if _storage and hasattr(_storage, "upsert_profile"):
        try:
            saved = _storage.upsert_profile(p.model_dump())
            return {"ok": True, "profile": saved}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return {"ok": True, "profile": p.model_dump(), "debug": {"storage": "not_configured"}}
