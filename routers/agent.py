from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/agent", tags=["agent"])

# Try to import root agent (agent.py in project root)
_root_agent = None
try:
    import agent as _root_agent  # type: ignore
except Exception:
    _root_agent = None

# Async search for fallback (no asyncio.run here)
try:
    from services.aggregator import search_events as _agg_search_async
except Exception:
    _agg_search_async = None  # type: ignore


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


# ---------- Fallback agent (async, uses aggregator) ----------

async def _fallback_agent(req: ChatRequest) -> ChatResponse:
    """
    Simple fallback when the LLM agent is unavailable or times out.
    Uses the async aggregator directly.
    """
    msg = (req.message or "").lower()

    # Only try an event search if the user clearly wants events
    search_terms = [
        "event", "concert", "show", "music", "sports", "festival"
    ]
    if any(word in msg for word in search_terms):
        city = (req.city or "Vilnius").strip()
        country = (req.country or "LT").strip() or "LT"

        if not _agg_search_async:
            return ChatResponse(
                ok=False,
                answer=(
                    "I tried to search for events, but the search "
                    "service is not configured."
                ),
                items=[],
                debug={
                    "fallback": True,
                    "source": "fallback",
                    "reason": "aggregator_not_available",
                    "city": city,
                    "country": country,
                },
            )

        try:
            result = await _agg_search_async(
                city=city,
                country=country,
                days_ahead=30,
                start_in_days=0,
                include_mock=True,
                query=None,
                limit=20,
                offset=0,
            )
        except Exception as exc:
            return ChatResponse(
                ok=False,
                answer=(
                    "I'm having trouble searching for events right now. "
                    "Please try again later."
                ),
                items=[],
                debug={
                    "fallback": True,
                    "source": "fallback",
                    "aggregator_error": repr(exc),
                    "city": city,
                    "country": country,
                },
            )

        items = (result or {}).get("items") or []
        items = items[:10]

        if items:
            return ChatResponse(
                ok=True,
                answer=(
                    f"I found {len(items)} events in {city}. "
                    f"Here are some options:"
                ),
                items=items,
                debug={
                    "fallback": True,
                    "source": "fallback",
                    "city": city,
                    "country": country,
                },
            )
        else:
            return ChatResponse(
                ok=True,
                answer=(
                    f"I couldn't find any events in {city} right now. "
                    f"Try widening your search or check back later."
                ),
                items=[],
                debug={
                    "fallback": True,
                    "source": "fallback",
                    "reason": "no_results",
                    "city": city,
                    "country": country,
                },
            )

    # Generic small-talk response
    return ChatResponse(
        ok=True,
        answer=(
            "I can help you find events and activities! "
            "Try asking about concerts, shows, or sports in your city."
        ),
        items=[],
        debug={"fallback": True, "source": "generic"},
    )


# ---------- Helper to call root agent in a thread ----------

def _call_root_agent(req: ChatRequest) -> Dict[str, Any]:
    """
    Synchronous wrapper around agent.chat(...) so we can run it in a thread.
    """
    if not _root_agent:
        raise RuntimeError("root_agent_not_available")

    # IMPORTANT: match the signature of agent.chat
    return _root_agent.chat(
        user_id=req.user_id,
        message=req.message,
        username=req.username,
        city=req.city,
        country=req.country,
    )


# ---------- Routes ----------

@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """
    Chat with the Socialite agent.

    - Prefer the root LLM agent (agent.chat) if available.
    - On timeout or error, fall back to a direct event search.
    """
    base_debug: Dict[str, Any] = {
        "root_agent_available": _root_agent is not None,
    }

    # Try the root LLM agent first, if present
    if _root_agent is not None:
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_call_root_agent, req)
                try:
                    # Allow enough time for 2 OpenAI calls + aggregator
                    result = future.result(timeout=45)
                except FuturesTimeout:
                    # LLM agent took too long -> fall back
                    fb = await _fallback_agent(req)
                    fb.debug.update(base_debug)
                    fb.debug.update({
                        "source": "fallback",
                        "root_agent_timeout": True,
                        "root_agent_error": None,
                    })
                    return fb

        except Exception as exc:
            # Any other exception from the LLM agent -> fall back
            fb = await _fallback_agent(req)
            fb.debug.update(base_debug)
            fb.debug.update({
                "source": "fallback",
                "root_agent_timeout": False,
                "root_agent_error": repr(exc),
            })
            return fb

        # If we reach here, root agent succeeded
        if not isinstance(result, dict):
            # Be defensive in case agent.chat returns something odd
            fb = await _fallback_agent(req)
            fb.debug.update(base_debug)
            fb.debug.update({
                "source": "fallback",
                "root_agent_timeout": False,
                "root_agent_error": "invalid_result_from_root_agent",
            })
            return fb

        answer = (result.get("answer") or result.get("reply") or "").strip()
        # Try to extract items from agent output if present
        items = result.get("items") or []
        if not items:
            last = result.get("last_tool_result") or {}
            items = last.get("items") or []

        dbg = result.get("debug") or {}
        dbg.update(base_debug)
        dbg.setdefault("source", "root_agent")
        dbg.setdefault("fallback", False)
        dbg.setdefault("root_agent_timeout", False)
        dbg.setdefault("root_agent_error", None)

        return ChatResponse(
            ok=True,
            answer=answer or "Here are some events I found for you:",
            items=items,
            debug=dbg,
        )

    # If no root agent at all -> pure fallback
    fb = await _fallback_agent(req)
    fb.debug.update(base_debug)
    return fb


@router.post("/subscribe")
async def subscribe(req: SubscribeRequest) -> Dict[str, Any]:
    """
    Subscribe to event digests. Currently returns a placeholder response.
    """
    return {
        "ok": True,
        "hint": "Subscriptions are not yet implemented. Check back later!",
        "user_id": req.user_id,
        "cadence": req.cadence,
    }


@router.get("/digest/{user_id}", response_model=DigestResponse)
async def get_digest(user_id: str) -> DigestResponse:
    """
    Get the latest digest for a user. Currently returns placeholder data.
    """
    return DigestResponse(
        digest=[
            {
                "title": "Sample Event",
                "note": "This is a placeholder digest. Real digests coming soon!",
            }
        ],
        generated_at="2024-01-01T00:00:00Z",
    )


@router.get("/status")
async def agent_status() -> Dict[str, Any]:
    """
    Get the status of available agent services.
    """
    return {
        "root_agent_available": _root_agent is not None,
        "fallback_enabled": True,
    }
