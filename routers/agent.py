from __future__ import annotations

import re
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/agent", tags=["agent"])

# --- optional dependencies ---
_services_agent = None
_root_agent = None
_agg_sync = None

try:
    from services import agent as _services_agent  # legacy text-only agent (optional)
except Exception:
    _services_agent = None

try:
    import agent as _root_agent  # root LLM agent in project root
except Exception:
    _root_agent = None

try:
    from services.aggregator import search_events_sync as _agg_sync
except Exception:
    _agg_sync = None


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


_EVENT_KEYWORDS = (
    "event", "events",
    "concert", "concerts",
    "show", "shows",
    "music",
    "sport", "sports",
    "festival", "festivals",
    "party", "parties",
)

# ---------- helpers ----------


def _run_aggregator_in_thread(
    *,
    city: str,
    country: str,
    days_ahead: int = 30,
    start_in_days: int = 0,
    include_mock: bool = True,
    query: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Safe wrapper around services.aggregator.search_events_sync.

    Runs it in a background thread so its internal asyncio.run() does NOT
    conflict with FastAPI's event loop.
    """
    if _agg_sync is None:
        return {
            "count": 0,
            "items": [],
            "debug": {"reason": "aggregator_unavailable"},
        }

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            _agg_sync,
            city=city,
            country=country,
            days_ahead=days_ahead,
            start_in_days=start_in_days,
            include_mock=include_mock,
            query=query,
        )
        try:
            result = future.result(timeout=25) or {}
            dbg = result.get("debug") or {}
            dbg["via"] = "thread_wrapper"
            result["debug"] = dbg
            return result
        except FuturesTimeout:
            return {
                "count": 0,
                "items": [],
                "debug": {"reason": "aggregator_timeout"},
            }
        except Exception as e:
            return {
                "count": 0,
                "items": [],
                "debug": {"reason": "aggregator_error", "error": str(e)},
            }


def _fallback_agent(req: ChatRequest, *, extra_debug: Optional[Dict[str, Any]] = None) -> ChatResponse:
    """
    Simple fallback when the LLM agent is unavailable or times out.
    Uses the aggregator (via thread wrapper) when the message looks
    event-related; otherwise returns a generic helper message.
    """
    msg = req.message.lower()
    debug: Dict[str, Any] = {"fallback": True}
    if extra_debug:
        debug.update(extra_debug)

    # If it looks like an events query, try the aggregator.
    if any(k in msg for k in _EVENT_KEYWORDS):
        city = (req.city or "Vilnius").strip() or "Vilnius"
        country = (req.country or "LT").strip() or "LT"

        data = _run_aggregator_in_thread(
            city=city,
            country=country,
            days_ahead=30,
            start_in_days=0,
            include_mock=True,
            query=None,
        )

        items = (data.get("items") or [])[:5]
        count = len(items)

        debug.update(data.get("debug") or {})
        debug.update(
            {
                "source": "aggregator",
                "city": city,
                "country": country,
            }
        )

        if count:
            answer = f"I found {count} events in {city}. Here are some options:"
            return ChatResponse(ok=True, answer=answer, items=items, debug=debug)
        else:
            answer = (
                f"I couldn't find any events in {city} right now. "
                f"Try widening your search or check back later."
            )
            return ChatResponse(ok=False, answer=answer, items=[], debug=debug)

    # Otherwise, generic guidance.
    debug["source"] = "generic"
    answer = (
        "I can help you find events and activities! "
        "Try asking something like “concerts this weekend in Vilnius” "
        "or use the Discover tab to browse events."
    )
    return ChatResponse(ok=True, answer=answer, items=[], debug=debug)


# ---------- Routes ----------


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """
    Chat with the Socialite agent. Tries, in order:
    1) root LLM agent (agent.py in project root)
    2) legacy services.agent (if present)
    3) simple fallback that calls the aggregator in a thread
    """
    root_debug: Dict[str, Any] = {}

    # 1) Root LLM agent (agent.py)
    if _root_agent is not None:
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    _root_agent.chat,
                    user_id=req.user_id,
                    message=req.message,
                    username=req.username,
                    city=req.city,
                    country=req.country,
                )
                result = future.result(timeout=45)
        except FuturesTimeout:
            root_debug["root_agent_timeout"] = True
        except Exception as e:
            root_debug["root_agent_error"] = str(e)
        else:
            if isinstance(result, dict):
                # Normalise the structure a bit
                answer = result.get("answer") or "Here's what I found."
                items = result.get("items") or []
                dbg = result.get("debug") or {}
                dbg.update(root_debug)
                dbg["source"] = "root_agent"
                ok = result.get("ok", True)
                return ChatResponse(ok=ok, answer=answer, items=items, debug=dbg)

    # 2) Legacy text-only services.agent (optional)
    if _services_agent is not None:
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    _services_agent,
                    req.message,
                    req.user_id,
                )
                text = future.result(timeout=20)
        except FuturesTimeout:
            root_debug["services_agent_timeout"] = True
        except Exception as e:
            root_debug["services_agent_error"] = str(e)
        else:
            dbg = {"source": "services_agent"}
            dbg.update(root_debug)
            return ChatResponse(ok=True, answer=text, items=[], debug=dbg)

    # 3) Fallback using aggregator (via thread wrapper)
    return _fallback_agent(req, extra_debug=root_debug)


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
        "services_agent_available": _services_agent is not None,
        "root_agent_available": _root_agent is not None,
        "aggregator_available": _agg_sync is not None,
        "fallback_enabled": True,
    }
