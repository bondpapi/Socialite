from __future__ import annotations

import re
from typing import Optional, Dict, Any, List, Tuple

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/agent", tags=["agent"])

# Optional real agent + scheduler 
_agent_impl = None
_digest_impl = None
try:
    from services import agent as _agent_impl
except Exception:
    _agent_impl = None

try:
    from services import scheduler as _digest_impl
except Exception:
    _digest_impl = None

# Lightweight fallback: call the aggregator directly
_agg_sync = None
try:
    from services.aggregator import search_events_sync as _agg_sync
except Exception:
    _agg_sync = None


# ----------------------------- models ---------------------------------

class ChatRequest(BaseModel):
    user_id: str
    message: str
    username: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    days_ahead: int = 120
    start_in_days: int = 0
    include_mock: bool = False
    limit: int = 30
    offset: int = 0


class SubscribeRequest(BaseModel):
    user_id: str
    city: str
    country: str
    cadence: str = "WEEKLY"  # e.g., DAILY/WEEKLY
    keywords: Optional[List[str]] = None


# ---------------------------- helpers ----------------------------------

_CITY_HINT = re.compile(r"\b(?:in|around|near)\s+([A-Za-zÀ-ž\-\.'\s]{2,})\b", re.I)
_COUNTRY_ISO2 = re.compile(r"\b(country|cc)\s*[:=]\s*([A-Za-z]{2})\b", re.I)

def _infer_city_country(message: str, fallback_city: Optional[str], fallback_country: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Very light heuristic:
      - "in Vilnius", "near Kaunas" → city
      - "country: LT" or "cc=LT" → ISO-2
    """
    city = fallback_city
    m = _CITY_HINT.search(message or "")
    if m:
        city = m.group(1).strip(" .,")

    country = (fallback_country or "")
    m2 = _COUNTRY_ISO2.search(message or "")
    if m2:
        country = m2.group(2).upper()

    return (city, country or None)


def _short_answer(city: Optional[str], country: Optional[str], total: int) -> str:
    loc = ", ".join([p for p in [city, country] if p])
    loc = f" in {loc}" if loc else ""
    noun = "event" if total == 1 else "events"
    return f"I found {total} {noun}{loc}. Here are a few you might like."


# ---------------------------- routes -----------------------------------

@router.post("/chat")
def chat(req: ChatRequest) -> Dict[str, Any]:
    """
    Chat with Socialite.
    - If a real agent service exists: delegate to it.
    - Otherwise: do a practical search via the aggregator and return items.
    """
    # 1) full LLM agent would take priority.
    if _agent_impl and hasattr(_agent_impl, "chat"):
        try:
            return _agent_impl.chat(
                user_id=req.user_id,
                message=req.message,
                username=req.username,
                city=req.city,
                country=req.country,
            )
        except Exception as e:
            return {
                "ok": False,
                "answer": "I hit a snag while generating a reply. Try rephrasing or narrowing the request.",
                "error": str(e),
            }

    # 2) Fallback: intent-lite → aggregator search
    if not _agg_sync:
        # Last-resort friendly message if aggregator import failed
        return {
            "ok": True,
            "answer": "I can search events if you tell me a city/country, a date window, or a type like music/sports/arts.",
            "debug": {"agent": "fallback", "reason": "aggregator_unavailable"},
        }

    # Infer location from text if not provided
    city, country = _infer_city_country(req.message, req.city, req.country)

    # If still missing, nudge user but do not fail
    if not city and not country:
        hint = ("Tell me a city (e.g., 'in Vilnius') and optionally a country code "
                "(e.g., 'country: LT'), plus any keywords.")
    else:
        hint = None

    # Use the whole user message as a keyword query (keeps it simple)
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

    total = int(payload.get("total") or payload.get("count") or 0)
    items = payload.get("items") or []

    return {
        "ok": True,
        "answer": _short_answer(city, country, total),
        "items": items,
        "debug": {
            "agent": "fallback_search",
            "city": city,
            "country": country,
            "limit": req.limit,
            "offset": req.offset,
            "window": payload.get("debug", {}).get("window"),
            "providers_used": payload.get("providers_used"),
            "provider_errors": payload.get("debug", {}).get("provider_errors"),
            "hint": hint,
        },
    }


@router.get("/digest/{user_id}")
def get_digest(user_id: str) -> Dict[str, Any]:
    """
    Return the latest digest for a user if a scheduler is present; otherwise a placeholder.
    """
    if _digest_impl and hasattr(_digest_impl, "latest_digest_for"):
        try:
            digest = _digest_impl.latest_digest_for(user_id)
            return {"ok": True, "digest": digest}
        except Exception as e:
            return {"ok": False, "digest": None, "error": str(e)}

    return {"ok": True, "digest": None, "debug": {"scheduler": "not_configured"}}


@router.post("/subscribe")
def subscribe(req: SubscribeRequest) -> Dict[str, Any]:
    """
    Subscribe the user to a periodic digest. If scheduler isn't available,
    acknowledge the request so the UI flow succeeds.
    """
    if _digest_impl and hasattr(_digest_impl, "subscribe"):
        try:
            _digest_impl.subscribe(
                user_id=req.user_id,
                city=req.city,
                country=req.country,
                cadence=req.cadence,
                keywords=req.keywords or [],
            )
            return {"ok": True, "subscribed": True}
        except Exception as e:
            return {"ok": False, "subscribed": False, "error": str(e)}

    return {
        "ok": True,
        "subscribed": False,
        "debug": {"scheduler": "not_configured"},
        "hint": "Scheduler not enabled on server; request accepted but not scheduled.",
    }
