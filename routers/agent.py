from __future__ import annotations

import os
import re
from typing import Optional, Dict, Any, List, Tuple

from fastapi import APIRouter
from pydantic import BaseModel

from services import http  # same HTTP helper you use in providers

router = APIRouter(prefix="/agent", tags=["agent"])

# -------------------------------------------------
# Internal API base (for calling /events/search)
# -------------------------------------------------
_api_port = os.getenv("API_PORT", "8000")
INTERNAL_API = os.getenv(
    "SOCIALITE_INTERNAL_API",
    f"http://127.0.0.1:{_api_port}"
).rstrip("/")

# -------------------------------------------------
# Models
# -------------------------------------------------


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


# -------------------------------------------------
# Helpers
# -------------------------------------------------

_EVENT_KEYWORDS = re.compile(
    r"\b(event|events|concert|show|gig|music|festival|party|"
    r"sport|sports|game|match|comedy|theatre|theater|exhibition|museum)\b",
    re.IGNORECASE,
)


def _infer_city_country(req: ChatRequest) -> Tuple[str, str]:
    city = (req.city or "").strip()
    country = (req.country or "").strip()

    if not city:
        city = "Vilnius"  # sensible default
    if not country:
        country = "LT"

    return city, country.upper()[:2]


def _search_events_via_api(
    *, city: str, country: str, query: Optional[str] = None
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Call our own /events/search endpoint inside the container so that the agent
    reuses the same aggregator logic as /events/search and Discover.
    """
    params: Dict[str, Any] = {
        "city": city,
        "country": country,
        "days_ahead": 30,    
        "start_in_days": 0,
        "include_mock": True,
        "limit": 20,
        "offset": 0,
    }
    if query:
        params["query"] = query

    resp = http.get(
        f"{INTERNAL_API}/events/search",
        params=params,
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json() or {}
    return data, params


# -------------------------------------------------
# Fallback agent
# -------------------------------------------------


def _fallback_agent(req: ChatRequest) -> ChatResponse:
    """
    Simple, robust agent that:
      - Detects if the user is asking about events
      - Calls /events/search internally
      - Returns a short natural-language answer + top events
    """
    message_lower = req.message.lower()

    # If user is not clearly asking about events, give guidance instead of calling search
    if not _EVENT_KEYWORDS.search(message_lower):
        return ChatResponse(
            ok=True,
            answer=(
                "I can help you discover events and activities. "
                "Try something like:\n"
                "- 'concerts this weekend in Vilnius'\n"
                "- 'family events tomorrow'\n"
                "- 'comedy shows next month in Kaunas'"
            ),
            items=[],
            debug={"fallback": True, "reason": "no_event_keywords"},
        )

    city, country = _infer_city_country(req)

    try:
        data, sent_params = _search_events_via_api(
            city=city,
            country=country,
            query=None,
        )
        items = data.get("items") or []

        if not items:
            answer = (
                f"I couldn't find any events in {city} over the next 30 days. "
                "Try widening the search window in Settings."
            )
            return ChatResponse(
                ok=True,
                answer=answer,
                items=[],
                debug={
                    "fallback": True,
                    "city": city,
                    "country": country,
                    "sent_params": sent_params,
                    "raw_response": data,
                },
            )

        # Trim to a small set for the chat UI
        top_items = items[:5]
        answer = (
            f"I found {len(items)} events in {city} over the next 30 days. "
            "Here are a few picks:"
        )
        return ChatResponse(
            ok=True,
            answer=answer,
            items=top_items,
            debug={
                "fallback": True,
                "city": city,
                "country": country,
                "sent_params": sent_params,
                "raw_count": data.get("count"),
            },
        )

    except Exception as e:
        # Any error in search – return a friendly message plus debug
        return ChatResponse(
            ok=True,
            answer=(
                "I'm having trouble searching for events right now. "
                "Please try again later."
            ),
            items=[],
            debug={
                "fallback": True,
                "error": str(e),
                "city": city,
                "country": country,
                "internal_api": INTERNAL_API,
            },
        )


# -------------------------------------------------
# Routes
# -------------------------------------------------


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """
    Chat with the Socialite agent.

    For now we always use the robust fallback that calls /events/search
    internally, so behaviour is consistent with the Discover tab.
    """
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
    Simple status endpoint so you can see from logs / curl what mode the agent is in.
    """
    return {
        "mode": "fallback_only",
        "internal_api": INTERNAL_API,
    }
