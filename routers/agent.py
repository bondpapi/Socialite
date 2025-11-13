from __future__ import annotations

from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.aggregator import search_events_sync

router = APIRouter(prefix="/agent", tags=["agent"])

# Try to import agent services
_services_agent = None
_root_agent = None

try:
    from ..services.agent import chat_with_agent
    _services_agent = chat_with_agent
except Exception:
    _services_agent = None

try:
    from ..services.root_agent import RootAgent
    _root_agent = RootAgent()
except Exception:
    _root_agent = None

# ---------- Models ----------


class ChatRequest(BaseModel):
    user_id: str
    username: Optional[str] = None
    message: str
    city: Optional[str] = None
    country: Optional[str] = None


class ChatResponse(BaseModel):
    ok: bool = True
    answer: str
    items: List[Dict[str, Any]] = []
    debug: Dict[str, Any] = {}


class SubscribeRequest(BaseModel):
    user_id: str
    city: Optional[str] = None
    country: Optional[str] = None
    cadence: str = "WEEKLY"  # WEEKLY, DAILY
    keywords: List[str] = []


class DigestResponse(BaseModel):
    digest: List[Dict[str, Any]] = []
    generated_at: Optional[str] = None

# ---------- Fallback agent ----------


def _fallback_agent(req: ChatRequest) -> ChatResponse:
    """Simple fallback when no LLM agent is available."""
    msg = req.message.lower()

    # Simple keyword matching
    if any(word in msg for word in ["event", "concert", "show", "music", "sports"]):
        city = req.city or "Vilnius"
        country = req.country or "LT"

        try:
            result = search_events_sync(
                city=city,
                country=country,
                days_ahead=30,
                start_in_days=0,
                include_mock=True
            )

            items = result.get("items", [])[:5]  # Take first 5
            count = len(items)

            if count > 0:
                answer = f"I found {count} events in {city}. Here are some options:"
            else:
                answer = f"I couldn't find any events in {city} right now. Try widening your search or check back later."

            return ChatResponse(
                answer=answer,
                items=items,
                debug={"fallback": True, "search_params": {
                    "city": city, "country": country}}
            )
        except Exception as e:
            return ChatResponse(
                answer="I'm having trouble searching for events right now. Please try again later.",
                debug={"fallback": True, "error": str(e)}
            )

    # Generic response
    return ChatResponse(
        answer="I can help you find events and activities! Try asking about concerts, shows, or sports in your city.",
        debug={"fallback": True, "generic": True}
    )

# ---------- Routes ----------


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """
    Chat with the Socialite agent. Falls back gracefully if no LLM agent is available.
    """
    try:
        # Try root agent first
        if _root_agent:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_root_agent.chat, req.dict())
                try:
                    result = future.result(timeout=30)
                    return ChatResponse(**result)
                except FuturesTimeout:
                    return ChatResponse(
                        answer="The agent took too long to respond. Please try a simpler question.",
                        debug={"timeout": True}
                    )

        # Try services agent
        elif _services_agent:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    _services_agent, req.message, req.user_id)
                try:
                    result = future.result(timeout=30)
                    return ChatResponse(answer=result, debug={"services_agent": True})
                except FuturesTimeout:
                    return ChatResponse(
                        answer="The agent took too long to respond. Please try again.",
                        debug={"timeout": True}
                    )

        # Fallback to simple agent
        else:
            return _fallback_agent(req)

    except Exception as e:
        # Always fall back to simple agent on any error
        return _fallback_agent(req)


@router.post("/subscribe")
async def subscribe(req: SubscribeRequest) -> Dict[str, Any]:
    """
    Subscribe to event digests. Currently returns a placeholder response.
    """
    return {
        "ok": True,
        "hint": "Subscriptions are not yet implemented. Check back later!",
        "user_id": req.user_id,
        "cadence": req.cadence
    }


@router.get("/digest/{user_id}", response_model=DigestResponse)
async def get_digest(user_id: str) -> DigestResponse:
    """
    Get the latest digest for a user. Currently returns placeholder data.
    """
    return DigestResponse(
        digest=[
            {"title": "Sample Event",
                "note": "This is a placeholder digest. Real digests coming soon!"}
        ],
        generated_at="2024-01-01T00:00:00Z"
    )


@router.get("/status")
async def agent_status() -> Dict[str, Any]:
    """
    Get the status of available agent services.
    """
    return {
        "services_agent_available": _services_agent is not None,
        "root_agent_available": _root_agent is not None,
        "fallback_enabled": True,
    }
