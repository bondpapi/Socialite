from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Optional, Dict, Any, List

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])

# Optional agents
_services_agent = None
_root_agent = None

try:
    # legacy/simple agent in services.agent (may or may not exist)
    from services import agent as _services_agent  # type: ignore
except Exception:
    _services_agent = None

try:
    # your new tools-based agent at project root (agent.py)
    import agent as _root_agent  # type: ignore
except Exception:
    _root_agent = None

# Aggregator sync helper (used by fallback)
try:
    from services.aggregator import search_events_sync as _agg_sync  # type: ignore
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


# ---------- Helpers ----------


def _normalize_root_result(result: Any) -> ChatResponse:
    """
    Take whatever root agent returns and normalize to ChatResponse.
    """
    if isinstance(result, ChatResponse):
        return result

    if isinstance(result, dict):
        items = result.get("items") or []
        debug = result.get("debug") or {}
        debug["agent"] = "root_agent"
        return ChatResponse(
            ok=bool(result.get("ok", True)),
            answer=result.get("answer")
            or "I’m not sure how to respond, but you can still use Discover to browse events.",
            items=items,
            debug=debug,
        )

    return ChatResponse(
        ok=False,
        answer="I couldn’t understand the agent’s response, but you can still use Discover to browse events.",
        debug={"agent": "root_agent", "raw_type": type(result).__name__},
    )


def _fallback_agent(req: ChatRequest) -> ChatResponse:
    """
    Simple, *fast* fallback that will never hang the HTTP request.
    If possible, it does a quick event search; otherwise returns helpful text.
    """
    msg = req.message.lower()
    wants_events = any(
        w in msg for w in ["event", "events", "concert", "show", "music", "sport", "sports", "festival"]
    )

    city = req.city or "Vilnius"
    country = (req.country or "LT").upper()

    # only try aggregator when:
    #  - user clearly wants events, and
    #  - we actually have the sync helper
    if wants_events and _agg_sync is not None:
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    _agg_sync,
                    city=city,
                    country=country,
                    days_ahead=30,
                    start_in_days=0,
                    include_mock=True,
                )
                # Hard 15s cap on fallback search
                result = future.result(timeout=15)

            result = result or {}
            items = result.get("items") or []
            count = len(items)

            if count:
                answer = f"I found {count} events in {city}. Here are a few ideas:"
            else:
                answer = (
                    f"I couldn’t find any events in {city} right now. "
                    f"Try widening the date range or changing the city."
                )

            return ChatResponse(
                ok=True,
                answer=answer,
                items=items[:5],
                debug={
                    "fallback": True,
                    "city": city,
                    "country": country,
                    "source": "aggregator",
                },
            )

        except FuturesTimeout:
            logger.warning("Fallback aggregator search timed out")
        except Exception as exc:
            logger.exception("Fallback aggregator search failed: %r", exc)

    # Generic / non-search fallback
    return ChatResponse(
        ok=True,
        answer=(
            "I can help you look for events and activities. "
            "Try asking something like “concerts this weekend in Vilnius” "
            "or use the Discover tab to browse events."
        ),
        debug={"fallback": True, "source": "generic"},
    )


# ---------- Routes ----------


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """
    Chat with the Socialite agent.
    We try the root tools-based agent first, then an optional legacy agent,
    and finally a fast fallback that never hangs.
    """
    # 1) Root agent (agent.py at project root) – tools + OpenAI
    if _root_agent is not None and hasattr(_root_agent, "chat"):
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
                # Hard cap so Render never hangs this endpoint forever
                result = future.result(timeout=25)

            return _normalize_root_result(result)

        except FuturesTimeout:
            logger.warning("root agent timed out for user %s", req.user_id)
            # fall through to fallback
        except Exception as exc:
            logger.exception("root agent error for user %s: %r", req.user_id, exc)
            # fall through to fallback

    # 2) Optional legacy services.agent.chat if present
    if _services_agent is not None and hasattr(_services_agent, "chat"):
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    _services_agent.chat,  # type: ignore[attr-defined]
                    req.message,
                    req.user_id,
                )
                result = future.result(timeout=10)

            if isinstance(result, str):
                return ChatResponse(
                    ok=True,
                    answer=result,
                    debug={"agent": "services.agent.chat"},
                )
            if isinstance(result, dict):
                return ChatResponse(
                    ok=bool(result.get("ok", True)),
                    answer=result.get("answer") or "",
                    items=result.get("items") or [],
                    debug={"agent": "services.agent.chat", **(result.get("debug") or {})},
                )
        except FuturesTimeout:
            logger.warning("services.agent.chat timed out for user %s", req.user_id)
        except Exception as exc:
            logger.exception("services.agent.chat error for user %s: %r", req.user_id, exc)

    # 3) Final fallback – simple, bounded, never hangs
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
        "services_agent_available": _services_agent is not None,
        "root_agent_available": _root_agent is not None,
        "aggregator_available": _agg_sync is not None,
        "fallback_enabled": True,
    }
