from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/agent", tags=["agent"])

# ---------- Optional integrations ----------

_services_agent = None
_root_agent = None
_agg_async = None

try:
    # root-level agent.py (LLM + tools)
    import agent as _root_agent  # type: ignore[assignment]
except Exception:
    _root_agent = None

try:
    # legacy services agent (string-in / string-out)
    from services import agent as _services_agent  # type: ignore[assignment]
except Exception:
    _services_agent = None

try:
    # async search API from aggregator
    from services.aggregator import (  # type: ignore[assignment]
        search_events as _agg_async
    )
except Exception:
    _agg_async = None


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


# ---------- Async fallback agent (no LLM, just aggregator) ----------


async def _fallback_agent(req: ChatRequest) -> ChatResponse:
    """
    Simple async fallback when the LLM agent is unavailable or times out.
    Uses the aggregator directly if possible.
    """
    msg = (req.message or "").lower()

    wants_events = any(
        w in msg
        for w in ["event", "concert", "show", "music", "sports", "festival"]
    )

    # If the user isn't obviously asking for events, just respond generically.
    if not wants_events or _agg_async is None:
        return ChatResponse(
            ok=False,
            answer=(
                "I can help you find events and activities! "
                "Try asking something like “concerts this weekend in Vilnius” "
                "or use the Discover tab to browse events."
            ),
            items=[],
            debug={"fallback": True, "source": "generic"},
        )

    city = req.city or "Vilnius"
    country = (req.country or "LT").upper()

    try:
        # Use a modest window so it stays fast
        result = await _agg_async(
            city=city,
            country=country,
            days_ahead=30,
            start_in_days=0,
            include_mock=True,
            limit=20,
            offset=0,
        )
        items = (result or {}).get("items") or []
        items = items[:5]  # show only top 5 in chat

        if items:
            return ChatResponse(
                ok=True,
                answer=(
                    f"I found {len(items)} events in {city}. "
                    "Here are some options:"
                ),
                items=items,
                debug={
                    "fallback": True,
                    "source": "aggregator",
                    "city": city,
                    "country": country,
                },
            )
        else:
            return ChatResponse(
                ok=False,
                answer=(
                    f"I couldn't find any events in {city} right now. "
                    "Try widening your search or check back later."
                ),
                items=[],
                debug={
                    "fallback": True,
                    "source": "aggregator",
                    "city": city,
                    "country": country,
                },
            )

    except Exception as e:
        return ChatResponse(
            ok=False,
            answer=(
                "I'm having trouble searching for events right now. "
                "Please try again later."
            ),
            items=[],
            debug={
                "fallback": True,
                "source": "aggregator_error",
                "error": str(e),
                "city": city,
                "country": country,
            },
        )


# ---------- Main chat route ----------


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """
    Chat with the Socialite agent.

    Order of preference:
    1. Root LLM agent (agent.py) with tools.
    2. Legacy services agent (if present).
    3. Async fallback that calls the aggregator directly.
    """
    # 1) Try root LLM agent if available
    if _root_agent is not None:
        loop = asyncio.get_running_loop()

        def _run_root_agent() -> Dict[str, Any]:
            return _root_agent.chat(
                user_id=req.user_id,
                message=req.message,
                username=req.username,
                city=req.city,
                country=req.country,
            )

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = loop.run_in_executor(executor, _run_root_agent)
                result = await asyncio.wait_for(future, timeout=45.0)

            if isinstance(result, dict):
                return ChatResponse(
                    ok=bool(result.get("ok", True)),
                    answer=result.get(
                        "answer",
                        (
                            "I couldn't find any events right now. "
                            "Try widening your search or check back later."
                        ),
                    ),
                    items=result.get("items") or [],
                    debug={
                        "source": "root_agent",
                        "used_tools": result.get("used_tools", []),
                    },
                )

        except asyncio.TimeoutError:
            return await _fallback_agent(
                req.copy(
                    update={
                        # note the timeout in debug
                        "message": req.message,
                    }
                )
            )
        except Exception as e:
            # Any other error → fall back as well
            return await _fallback_agent(
                req.copy(
                    update={
                        "message": req.message,
                    }
                )
            )

    # 2) Legacy services agent (string in → string out)
    if _services_agent is not None:
        loop = asyncio.get_running_loop()

        def _run_services_agent() -> str:
            return _services_agent(  # type: ignore[misc]
                req.message, req.user_id
            )

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = loop.run_in_executor(executor, _run_services_agent)
                text = await asyncio.wait_for(future, timeout=30.0)
            return ChatResponse(
                ok=True,
                answer=text,
                items=[],
                debug={"source": "services_agent"},
            )
        except (asyncio.TimeoutError, FuturesTimeout):
            return await _fallback_agent(req)
        except Exception:
            return await _fallback_agent(req)

    # 3) Pure fallback
    return await _fallback_agent(req)


# ---------- Subscriptions & digest (still placeholder) ----------


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
                "note": (
                    "This is a placeholder digest. "
                    "Real digests coming soon!"
                ),
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
        "aggregator_available": _agg_async is not None,
        "fallback_enabled": True,
    }
