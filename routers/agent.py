from __future__ import annotations

import re
from typing import Optional, Dict, Any, List, Tuple

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/agent", tags=["agent"])

# Use the same aggregator that powers Discover
try:
    from services.aggregator import search_events_sync as _agg_sync
except Exception:
    _agg_sync = None

# ---------- Models ----------


class ChatRequest(BaseModel):
    user_id: str
    message: str
    username: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    # optional window controls, with safe defaults
    days_ahead: int = 120
    start_in_days: int = 0
    include_mock: bool = False
    limit: int = 30
    offset: int = 0


class ChatResponse(BaseModel):
    ok: bool = True
    answer: str
    items: List[Dict[str, Any]] = Field(default_factory=list)
    debug: Dict[str, Any] = Field(default_factory=dict)


class SubscribeRequest(BaseModel):
    user_id: str
    city: Optional[str] = None
    country: Optional[str] = None
    cadence: str = "WEEKLY"  # WEEKLY, DAILY
    keywords: List[str] = Field(default_factory=list)


class DigestResponse(BaseModel):
    digest: List[Dict[str, Any]] = Field(default_factory=list)
    generated_at: Optional[str] = None


# ---------- Helpers ----------

_CITY_HINT = re.compile(r"\b(?:in|around|near)\s+([A-Za-zÀ-ž\-\.'\s]{2,})\b", re.I)
_COUNTRY_ISO2 = re.compile(r"\b(?:country|cc)\s*[:=]\s*([A-Za-z]{2})\b", re.I)


def _infer_city_country(
    message: str,
    fallback_city: Optional[str],
    fallback_country: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    """Infer city/country from the free-text message with fallbacks."""
    city = fallback_city
    m = _CITY_HINT.search(message or "")
    if m:
        city = m.group(1).strip(" .,")

    country = (fallback_country or "")
    m2 = _COUNTRY_ISO2.search(message or "")
    if m2:
        country = m2.group(1).upper()

    return (city, country or None)


def _short_answer(city: Optional[str], country: Optional[str], total: int) -> str:
    loc = ", ".join([p for p in [city, country] if p])
    loc = f" in {loc}" if loc else ""
    noun = "event" if total == 1 else "events"
    if total == 0:
        return f"I couldn’t find any events{loc} for that request."
    return f"I found {total} {noun}{loc}. Here are some picks."


# ---------- Routes ----------


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """
    Simple agent:
    - infers city/country from the message + profile,
    - calls the same aggregator used by Discover,
    - returns a short summary + the event list.
    """
    if not _agg_sync:
        return ChatResponse(
            ok=False,
            answer="The search engine is unavailable right now.",
            debug={"error": "aggregator_unavailable"},
        )

    city, country = _infer_city_country(req.message, req.city, req.country)

    try:
        payload = _agg_sync(
            city=city or (req.city or ""),
            country=(country or req.country or "LT"),
            days_ahead=req.days_ahead,
            start_in_days=req.start_in_days,
            include_mock=req.include_mock,
            query=req.message,
            limit=req.limit,
            offset=req.offset,
        )
    except Exception as e:
        return ChatResponse(
            ok=False,
            answer="I'm having trouble searching for events right now. Please try again later.",
            debug={"error": str(e)},
        )

    items = payload.get("items") or []
    total = int(payload.get("total") or payload.get("count") or len(items))

    return ChatResponse(
        ok=True,
        answer=_short_answer(city, country, total),
        items=items,
        debug={
            "agent": "simple_aggregator",
            "providers_used": payload.get("providers_used"),
            "provider_errors": (payload.get("debug") or {}).get(
                "provider_errors"
            ),
            "window": (payload.get("debug") or {}).get("window"),
        },
    )


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
    Only the aggregator-backed simple agent is used now.
    """
    return {
        "aggregator_available": _agg_sync is not None,
        "fallback_enabled": True,
    }
