from __future__ import annotations
import hashlib
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str


@router.post("/mock-login")
def mock_login(payload: LoginIn) -> dict:
    # deterministic user_id from username
    h = hashlib.sha1(payload.username.encode("utf-8")).hexdigest()[:10]
    return {"user_id": f"user_{h}"}
