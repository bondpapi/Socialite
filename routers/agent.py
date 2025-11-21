from __future__ import annotations

import logging
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])

# Optional imports – we fall back gracefully if any are missing
_services_agent = None
_root_agent = None
try:
    from services import agent as _services_agent
except Exception:
    _services_agent = None

try:
    # root-level agent.py (the OpenAI / tools agent you just showed)
    import agent as _root_agent
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


# ---------- Fallback agent ----------

def _fallback_agent(req: ChatRequest) -> ChatResponse:
    """Simple fallback when no LLM agent is available OR when it errors."""
    msg = req.message.lower()

    # If aggregator is not available, just answer generically
    if _agg_sync is None:
        return ChatResponse(
            answer=(
                "I can help you find events in your city, but the search engine "
                "is temporarily unavailable. Please try again later."
            ),
            debug={"fallback": True, "search_available": False},
        )

    # Simple keyword matching to decide whether to try a search
    if any(word in msg for word in ["event", "concert", "show", "music", "sports"]):
        city = req.city or "Vilnius"
        country = req.country or "LT"

        try:
            result = _agg_sync(
                city=city,
                country=country,
                days_ahead=30,
                start_in_days=0,
                include_mock=True,
            )

            items = result.get("items", [])[:5]  # Take first 5
            count = len(items)

            if count > 0:
                answer = f"I found {count} events in {city}. Here are some options:"
            else:
                answer = (
                    f"I couldn't find any events in {city} right now. "
                    "Try widening your search or check back later."
                )

            return ChatResponse(
                answer=answer,
                items=items,
                debug={
                    "fallback": True,
                    "search_params": {"city": city, "country": country},
                    "raw": result,
                },
            )
        except Exception as e:
            logger.exception("Fallback search failed")
            return ChatResponse(
                answer=(
                    "I'm having trouble searching for events right now. "
                    "Please try again later."
                ),
                debug={"fallback": True, "error": str(e)},
            )

    # Generic response when the message is not obviously a search query
    return ChatResponse(
        answer=(
            "I can help you find events and activities! "
            "Try asking about concerts, shows, or sports in your city."
        ),
        debug={"fallback": True, "generic": True},
    )


# ---------- Routes ----------

@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """
    Chat with the Socialite agent.

    Priority:
      1. Root agent (agent.py with OpenAI + tools)
      2. services.agent (if present, legacy)
      3. Simple fallback agent
    """
    # 1) Root agent (your OpenAI + tools agent.py)
    if _root_agent is not None:
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                # >>> THIS IS THE SNIPPET YOU ASKED ABOUT <<<
                future = executor.submit(
                    _root_agent.chat,
                    user_id=req.user_id,
                    message=req.message,
                    username=req.username,
                    city=req.city,
                    country=req.country,
                )
                try:
                    result = future.result(timeout=30)
                except FuturesTimeout:
                    logger.warning("root_agent.chat timed out")
                    return ChatResponse(
                        answer=(
                            "The agent took too long to respond. "
                            "Please try a simpler question or try again in a moment."
                        ),
                        debug={"timeout": True, "root_agent": True},
                    )

            if isinstance(result, dict):
                answer = (
                    result.get("answer")
                    or "I had some trouble understanding that, but I'm here to help with events."
                )
                items = result.get("items") or []
                debug: Dict[str, Any] = {"root_agent": True}

                if "debug" in result:
                    debug["agent_debug"] = result["debug"]
                if "used_tools" in result:
                    debug["used_tools"] = result["used_tools"]

                return ChatResponse(answer=answer, items=items, debug=debug)

            # Unexpected type – fall through to fallback
            logger.warning("root_agent returned non-dict result: %r", type(result))
        except Exception as e:
            logger.exception("root_agent.chat failed: %s", e)
        # On any error, drop to fallback
        return _fallback_agent(req)

    # 2) services.agent (legacy simple agent, if you ever wire one up)
    if _services_agent is not None:
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                # Assuming services.agent exposes a callable like `run(message, user_id)`
                future = executor.submit(_services_agent, req.message, req.user_id)
                try:
                    text = future.result(timeout=30)
                except FuturesTimeout:
                    logger.warning("services_agent timed out")
                    return ChatResponse(
                        answer=(
                            "The agent took too long to respond. "
                            "Please try again."
                        ),
                        debug={"timeout": True, "services_agent": True},
                    )

            return ChatResponse(
                answer=text,
                debug={"services_agent": True},
            )
        except Exception as e:
            logger.exception("services_agent failed: %s", e)
            return _fallback_agent(req)

    # 3) Fallback agent
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
