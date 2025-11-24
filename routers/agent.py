from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/agent", tags=["agent"])

# --- Optional imports (root agent + services agent + aggregator) ----------------

_root_agent = None
_services_agent_chat = None
_search_events_sync = None

# Root-level agent (agent.py at repo root)
try:
    import agent as _root_agent  # must define chat(...)
except Exception:
    _root_agent = None

# Optional services-level agent (services/agent.py) – if you ever add one
try:
    from services.agent import chat as _services_agent_chat
except Exception:
    _services_agent_chat = None

# Aggregator for simple fallback search
try:
    from services.aggregator import search_events_sync as _search_events_sync
except Exception:
    _search_events_sync = None


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


# ---------- Fallback agent (no LLM required) ----------

def _fallback_agent(req: ChatRequest) -> ChatResponse:
    """
    Simple, robust fallback:
    - If the message looks like an event search and the aggregator is available,
      call /events via search_events_sync.
    - Otherwise, return a generic helper message.
    """
    msg = (req.message or "").lower()

    # If we have the aggregator, try to actually search for events
    if _search_events_sync and any(
        word in msg for word in ["event", "concert", "show", "music", "sport", "sports"]
    ):
        city = req.city or "Vilnius"
        country = req.country or "LT"

        try:
            result = _search_events_sync(
                city=city,
                country=country,
                days_ahead=30,
                start_in_days=0,
                include_mock=True,
                query=None,
            )
            items = result.get("items", [])[:5]
            count = len(items)

            if count > 0:
                answer = f"I found {count} events in {city}. Here are some options:"
            else:
                answer = (
                    f"I couldn't find any events in {city} right now. "
                    "Try widening your date range or changing your city."
                )

            return ChatResponse(
                ok=True,
                answer=answer,
                items=items,
                debug={
                    "fallback": True,
                    "source": "aggregator",
                    "city": city,
                    "country": country,
                },
            )
        except Exception as e:
            # If even the aggregator blows up, fall through to generic
            return ChatResponse(
                ok=False,
                answer="I'm having trouble searching for events right now. Please try again later.",
                items=[],
                debug={
                    "fallback": True,
                    "source": "aggregator_error",
                    "error": str(e),
                },
            )

    # Purely generic helper
    return ChatResponse(
        ok=True,
        answer=(
            "I can help you look for events and activities. "
            "Try asking something like “concerts this weekend in Vilnius” "
            "or use the Discover tab to browse events."
        ),
        items=[],
        debug={
            "fallback": True,
            "source": "generic",
        },
    )


# ---------- Routes ----------

@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """
    Chat with the Socialite agent.

    Priority:
    1. Root agent (agent.py) if available
    2. services.agent.chat if available
    3. Fallback agent (no LLM)
    """
    # --- 1) Root-level agent (your LLM tools agent.py) ---
    if _root_agent is not None:
        try:
            # IMPORTANT: call with keyword args, matching your agent.chat signature
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    _root_agent.chat,
                    user_id=req.user_id,
                    message=req.message,
                    username=req.username,
                    city=req.city,
                    country=req.country,
                )
                result = future.result(timeout=40)  # slightly under Streamlit's 60s

            # Normalise response into ChatResponse
            answer = (
                result.get("answer")
                or result.get("reply")
                or "I’m not sure how to respond to that."
            )
            items = result.get("items") or result.get("events") or []
            debug = result.get("debug") or {}
            debug.setdefault("source", "root_agent")

            return ChatResponse(ok=True, answer=answer, items=items, debug=debug)

        except FuturesTimeout:
            # LLM took too long – fall back but *say why*
            fb = _fallback_agent(req)
            fb.debug.setdefault("source", "root_agent_timeout")
            fb.debug["root_agent_timeout"] = True
            return fb

        except Exception as e:
            # Any other error from root agent – fall back and surface the error
            fb = _fallback_agent(req)
            fb.debug.setdefault("source", "root_agent_error")
            fb.debug["error"] = str(e)
            return fb

    # --- 2) Optional services.agent.chat (if you add one later) ---
    if _services_agent_chat is not None:
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    _services_agent_chat, req.message, req.user_id
                )
                text = future.result(timeout=30)

            return ChatResponse(
                ok=True,
                answer=text,
                items=[],
                debug={"source": "services_agent"},
            )

        except FuturesTimeout:
            fb = _fallback_agent(req)
            fb.debug.setdefault("source", "services_agent_timeout")
            fb.debug["services_agent_timeout"] = True
            return fb

        except Exception as e:
            fb = _fallback_agent(req)
            fb.debug.setdefault("source", "services_agent_error")
            fb.debug["error"] = str(e)
            return fb

    # --- 3) Pure fallback ---
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
        "services_agent_available": _services_agent_chat is not None,
        "root_agent_available": _root_agent is not None,
        "aggregator_available": _search_events_sync is not None,
        "fallback_enabled": True,
    }
