from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

router = APIRouter(prefix="/agent", tags=["agent"])

_agent_impl = None
_digest_impl = None
try:
    from services import agent as _agent_impl
except Exception:
    pass

try:
    from services import scheduler as _digest_impl
except Exception:
    pass


class ChatRequest(BaseModel):
    user_id: str
    message: str
    username: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None


@router.post("/chat")
def chat(req: ChatRequest) -> Dict[str, Any]:
    """
    Chat with Socialite agent. If your real agent isn't wired yet, returns a
    graceful fallback with guidance.
    """
    if _agent_impl and hasattr(_agent_impl, "chat"):
        try:
            return _agent_impl.chat(
                user_id=req.user_id,
                message=req.message,
                username=req.username,
                city=req.city,
                country=req.country,
            )
        except Exception as e:
            # Never blow up the API for agent errors—return a friendly message
            return {
                "ok": False,
                "answer": "It seems I hit a snag while generating a reply. Try rephrasing or narrowing the request.",
                "error": str(e),
            }

    # Fallback behavior if no service wired
    return {
        "ok": True,
        "answer": "I can search events if you tell me a city/country, a date window, or a type like music/sports/arts. "
                  "(Note: agent backend isn't connected; event search still works via /events/search.)",
        "debug": {"agent": "not_configured"},
    }


@router.get("/digest/{user_id}")
def get_digest(user_id: str) -> Dict[str, Any]:
    """
    Return the latest digest for a user if your scheduler built one; otherwise,
    return an informative placeholder so the UI doesn't break.
    """
    if _digest_impl and hasattr(_digest_impl, "latest_digest_for"):
        try:
            digest = _digest_impl.latest_digest_for(user_id)
            return {"ok": True, "digest": digest}
        except Exception as e:
            return {"ok": False, "digest": None, "error": str(e)}

    return {"ok": True, "digest": None, "debug": {"scheduler": "not_configured"}}


class SubscribeRequest(BaseModel):
    user_id: str
    city: str
    country: str
    cadence: str = "WEEKLY"  # e.g., DAILY/WEEKLY
    keywords: Optional[List[str]] = None


@router.post("/subscribe")
def subscribe(req: SubscribeRequest) -> Dict[str, Any]:
    """
    Subscribe the user to a periodic digest. If a scheduler isn't available,
    acknowledge the request so the UI flow succeeds.
    """
    if _digest_impl and hasattr(_digest_impl, "subscribe"):
        try:
            _digest_impl.subscribe(
                user_id=req.user_id,
                city=req.city,
                country=req.country,
                cadence=req.cadence,
                keywords=req.keywords or [],
            )
            return {"ok": True, "subscribed": True}
        except Exception as e:
            return {"ok": False, "subscribed": False, "error": str(e)}

    return {
        "ok": True,
        "subscribed": False,
        "debug": {"scheduler": "not_configured"},
        "hint": "Scheduler not enabled on server; request accepted but not scheduled.",
    }
