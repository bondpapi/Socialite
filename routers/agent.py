from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/agent", tags=["agent"])

# Try to import root agent: agent.py in project root
_root_agent = None
try:
    import agent as _root_agent  # type: ignore
except Exception:
    _root_agent = None

# Async search fallback
try:
    from services.aggregator import search_events as _agg_search_async
except Exception:
    _agg_search_async = None  # type: ignore


# ---------- Models ----------

class ChatRequest(BaseModel):
    user_id: str = "demo-user"
    username: Optional[str] = "demo"
    message: str
    city: Optional[str] = None
    country: Optional[str] = None
    days_ahead: Optional[int] = 120
    start_in_days: Optional[int] = 0
    keywords: Optional[str] = None
    passions: List[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    ok: bool = True
    answer: str = ""
    items: List[Dict[str, Any]] = Field(default_factory=list)
    debug: Dict[str, Any] = Field(default_factory=dict)


class SubscribeRequest(BaseModel):
    user_id: str
    city: Optional[str] = None
    country: Optional[str] = None
    cadence: str = "WEEKLY"
    keywords: List[str] = Field(default_factory=list)


class DigestResponse(BaseModel):
    digest: List[Dict[str, Any]] = Field(default_factory=list)
    generated_at: Optional[str] = None


# ---------- Helpers ----------

def _coerce_country(value: Optional[str]) -> str:
    return (value or "LT").strip().upper()[:2] or "LT"


def _agent_result_to_dict(result: Any) -> Dict[str, Any]:
    """
    Normalize whatever root agent returns into a dictionary.

    Supports:
    - plain dict
    - Pydantic model with model_dump()
    - object with reply/answer/items attributes
    """
    if isinstance(result, dict):
        return result

    if hasattr(result, "model_dump"):
        try:
            return result.model_dump()
        except Exception:
            pass

    data: Dict[str, Any] = {}

    for key in ("ok", "answer", "reply", "items", "used_tools", "error"):
        if hasattr(result, key):
            data[key] = getattr(result, key)

    return data


def _message_looks_like_event_search(message: str) -> bool:
    msg = (message or "").lower()
    search_terms = [
        "event",
        "events",
        "concert",
        "concerts",
        "show",
        "shows",
        "music",
        "sports",
        "festival",
        "festivals",
        "party",
        "parties",
        "weekend",
        "tonight",
        "tomorrow",
        "activity",
        "activities",
        "things to do",
    ]
    return any(term in msg for term in search_terms)


# ---------- Fallback agent ----------

async def _fallback_agent(req: ChatRequest) -> ChatResponse:
    """
    Simple fallback when the LLM agent is unavailable or times out.
    Uses the async aggregator directly.
    """
    msg = req.message or ""

    if _message_looks_like_event_search(msg):
        city = (req.city or "Vilnius").strip()
        country = _coerce_country(req.country)

        if not _agg_search_async:
            return ChatResponse(
                ok=False,
                answer=(
                    "I tried to search for events, but the search service "
                    "is not configured."
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
                days_ahead=int(req.days_ahead or 120),
                start_in_days=int(req.start_in_days or 0),
                include_mock=True,
                query=req.keywords,
                limit=50,
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
                answer=f"I found {len(items)} events in {city}. Here are some options:",
                items=items,
                debug={
                    "fallback": True,
                    "source": "fallback",
                    "city": city,
                    "country": country,
                    "count": len(items),
                },
            )

        return ChatResponse(
            ok=True,
            answer=(
                f"I couldn't find any events in {city} right now. "
                "Try widening your search window or clearing keywords in Settings."
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

    return ChatResponse(
        ok=True,
        answer=(
            "I can help you find events and activities. "
            "Try asking something like: 'concerts this weekend in my city'."
        ),
        items=[],
        debug={"fallback": True, "source": "generic"},
    )


# ---------- Root agent caller ----------

def _call_root_agent(req: ChatRequest) -> Dict[str, Any]:
    """
    Synchronous wrapper around the root agent.

    Supports both:
    - agent.chat(...)
    - agent.run_agent(...)
    """
    if not _root_agent:
        raise RuntimeError("root_agent_not_available")

    if hasattr(_root_agent, "chat"):
        result = _root_agent.chat(
            user_id=req.user_id,
            message=req.message,
            username=req.username,
            city=req.city,
            country=req.country,
            days_ahead=req.days_ahead,
            start_in_days=req.start_in_days,
            keywords=req.keywords,
            passions=req.passions,
        )
        return _agent_result_to_dict(result)

    if hasattr(_root_agent, "run_agent"):
        result = _root_agent.run_agent(
            user_id=req.user_id,
            message=req.message,
        )
        return _agent_result_to_dict(result)

    raise RuntimeError("root_agent_has_no_chat_or_run_agent")


# ---------- Routes ----------

@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """
    Chat with the Socialite agent.

    Flow:
    1. Try root LLM agent.
    2. If missing, broken, or timed out, fall back to direct event search.
    3. Always return FastHTML-friendly shape:
       { ok, answer, items, debug }
    """
    base_debug: Dict[str, Any] = {
        "root_agent_available": _root_agent is not None,
        "root_agent_has_chat": bool(_root_agent and hasattr(_root_agent, "chat")),
        "root_agent_has_run_agent": bool(_root_agent and hasattr(_root_agent, "run_agent")),
    }

    if _root_agent is not None:
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_call_root_agent, req)

                try:
                    result = future.result(timeout=45)
                except FuturesTimeout:
                    fb = await _fallback_agent(req)
                    fb.debug.update(base_debug)
                    fb.debug.update(
                        {
                            "source": "fallback",
                            "root_agent_timeout": True,
                            "root_agent_error": None,
                        }
                    )
                    return fb

        except Exception as exc:
            fb = await _fallback_agent(req)
            fb.debug.update(base_debug)
            fb.debug.update(
                {
                    "source": "fallback",
                    "root_agent_timeout": False,
                    "root_agent_error": repr(exc),
                }
            )
            return fb

        if not isinstance(result, dict):
            fb = await _fallback_agent(req)
            fb.debug.update(base_debug)
            fb.debug.update(
                {
                    "source": "fallback",
                    "root_agent_timeout": False,
                    "root_agent_error": "invalid_result_from_root_agent",
                }
            )
            return fb

        answer = (
            result.get("answer")
            or result.get("reply")
            or ""
        ).strip()

        items = result.get("items") or []

        if not items:
            last = result.get("last_tool_result") or {}
            if isinstance(last, dict):
                items = last.get("items") or []

        debug = result.get("debug") or {}
        if not isinstance(debug, dict):
            debug = {}

        debug.update(base_debug)
        debug.setdefault("source", "root_agent")
        debug.setdefault("fallback", False)
        debug.setdefault("root_agent_timeout", False)
        debug.setdefault("root_agent_error", None)

        return ChatResponse(
            ok=bool(result.get("ok", True)),
            answer=answer or "I processed your message, but did not get a detailed reply.",
            items=items,
            debug=debug,
        )

    fb = await _fallback_agent(req)
    fb.debug.update(base_debug)
    return fb


@router.post("/subscribe")
async def subscribe(req: SubscribeRequest) -> Dict[str, Any]:
    return {
        "ok": True,
        "hint": "Subscriptions are not yet implemented. Check back later!",
        "user_id": req.user_id,
        "cadence": req.cadence,
    }


@router.get("/digest/{user_id}", response_model=DigestResponse)
async def get_digest(user_id: str) -> DigestResponse:
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
    return {
        "root_agent_available": _root_agent is not None,
        "root_agent_has_chat": bool(_root_agent and hasattr(_root_agent, "chat")),
        "root_agent_has_run_agent": bool(_root_agent and hasattr(_root_agent, "run_agent")),
        "fallback_enabled": True,
    }