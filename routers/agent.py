from __future__ import annotations

import re
from typing import Optional, Dict, Any, List, Tuple
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/agent", tags=["agent"])

_services_agent = None
_root_agent = None
try:
    from services import agent as _services_agent
except Exception:
    _services_agent = None

try:
    import agent as _root_agent
except Exception:
    _root_agent = None

_agg_sync = None
try:
    from services.aggregator import search_events_sync as _agg_sync
except Exception:
    _agg_sync = None


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
    cadence: str = "WEEKLY"
    keywords: Optional[List[str]] = None


_CITY_HINT = re.compile(r"\b(?:in|around|near)\s+([A-Za-zÀ-ž\-\.'\s]{2,})\b", re.I)
_COUNTRY_ISO2 = re.compile(r"\b(?:country|cc)\s*[:=]\s*([A-Za-z]{2})\b", re.I)

def _infer_city_country(message: str, fallback_city: Optional[str], fallback_country: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
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
    return f"I found {total} {noun}{loc}. Here are some picks."

_EXEC = ThreadPoolExecutor(max_workers=1)

@router.post("/chat")
def chat(req: ChatRequest) -> Dict[str, Any]:
    """
    Try a real agent (services.agent or root agent) with a hard timeout.
    On timeout/error, fall back to aggregator so the UI never waits > ~18s.
    """
    # 1) If you later add services.agent.chat(), prefer it
    if _services_agent and hasattr(_services_agent, "chat"):
        try:
            fut = _EXEC.submit(_services_agent.chat,
                               user_id=req.user_id,
                               message=req.message,
                               username=req.username,
                               city=req.city,
                               country=req.country)
            result = fut.result(timeout=18)
            return result
        except FuturesTimeout:
            pass
        except Exception as e:
            # continue to fallback
            pass

    # 2) Root agent with timeout
    if _root_agent and hasattr(_root_agent, "run_agent"):
        try:
            fut = _EXEC.submit(_root_agent.run_agent, req.user_id, req.message)
            turn = fut.result(timeout=18)
            last = getattr(turn, "last_tool_result", None) or {}
            items = last.get("items") or []
            total = last.get("total") or last.get("count") or len(items)
            return {
                "ok": True,
                "answer": turn.reply,
                "items": items,
                "debug": {
                    "agent": "root_agent",
                    "used_tools": getattr(turn, "used_tools", []),
                    "provider_errors": (last.get("debug") or {}).get("provider_errors"),
                    "providers_used": last.get("providers_used"),
                },
            }
        except FuturesTimeout:
            # timed out — fall through to aggregator
            pass
        except Exception:
            # any agent error — fall through to aggregator
            pass

    # 3) Fallback: direct aggregator search (fast & reliable)
    if not _agg_sync:
        return {
            "ok": True,
            "answer": "Tell me a city (e.g., 'in Vilnius') and optionally 'country: LT', plus keywords.",
            "debug": {"agent": "fallback", "reason": "aggregator_unavailable"},
        }

    city, country = _infer_city_country(req.message, req.city, req.country)
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
    return {
        "ok": True,
        "answer": _short_answer(city, country, total),
        "items": payload.get("items") or [],
        "debug": {
            "agent": "fallback_search",
            "providers_used": payload.get("providers_used"),
            "provider_errors": (payload.get("debug") or {}).get("provider_errors"),
            "window": (payload.get("debug") or {}).get("window"),
        },
    }

@router.get("/digest/{user_id}")
def get_digest(user_id: str) -> Dict[str, Any]:
    return {"ok": True, "digest": None, "debug": {"scheduler": "not_configured"}}

@router.post("/subscribe")
def subscribe(req: SubscribeRequest) -> Dict[str, Any]:
    return {
        "ok": True,
        "subscribed": False,
        "debug": {"scheduler": "not_configured"},
        "hint": "Scheduler not enabled on server; request accepted but not scheduled.",
    }
