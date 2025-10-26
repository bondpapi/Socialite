from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, Dict, Any

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    user_id: str
    username: Optional[str] = None


@router.post("/login")
def login(req: LoginRequest) -> Dict[str, Any]:
    """
    Mock login that echoes a token-like payload for the UI.
    Replace with real auth later if needed.
    """
    return {
        "ok": True,
        "user_id": req.user_id,
        "username": req.username or req.user_id,
        "token": f"mock-{req.user_id}",
    }
