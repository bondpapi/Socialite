from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List

from services import storage

router = APIRouter(prefix="/profile", tags=["profile"])


class ProfileIn(BaseModel):
    home_city: Optional[str] = None
    home_country: Optional[str] = None
    passions: Optional[List[str]] = None


@router.get("/{user_id}")
def get_profile(user_id: str) -> dict:
    return storage.get_preferences(user_id) or {}


@router.post("/{user_id}")
def save_profile(user_id: str, payload: ProfileIn) -> dict:
    storage.save_preferences(
        user_id=user_id,
        home_city=payload.home_city,
        home_country=payload.home_country,
        passions=payload.passions or [],
    )
    return {"ok": True}
