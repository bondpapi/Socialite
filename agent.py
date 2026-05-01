from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from openai import APIError, APITimeoutError, OpenAI, RateLimitError
from pydantic import BaseModel, Field

from services import rag, storage
from services.aggregator import search_events_sync

_client = OpenAI(timeout=20, max_retries=1)

SYSTEM_PROMPT = (
    """You are Socialite — a friendly, efficient AI agent that finds
and plans real-world events. You:
- ask quick clarifying questions when needed,
- use tools to search events (never guess),
- use the knowledge search tool for background info about cities,
  venues, safety, prices, and general "how/why" questions,
- tailor suggestions to the user's saved city, country, passions and """
    """past likes,
- provide actionable plans (titles, venues, dates, links),
- keep replies concise and scannable with bullets.

When you use the event search tool:
- summarize key options in natural language,
- and rely on the tool's `items` list for concrete event details
  (titles, venues, dates, links, prices).

When you use the knowledge search tool:
- read the returned `hits` list and cite relevant details in
  your own words (do NOT just dump the raw JSON).

If the user asks for a digest or notifications, call the subscribe tool.
"""
)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "tool_search_events",
            "description": (
                "Search events for a city/country with optional "
                "keyword filters."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "country": {
                        "type": "string",
                        "description": "ISO-2 country code (e.g. LT, LV, EE, US).",
                    },
                    "days_ahead": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 365,
                        "default": 30,
                    },
                    "start_in_days": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 365,
                        "default": 0,
                    },
                    "include_mock": {"type": "boolean", "default": False},
                    "query": {
                        "type": "string",
                        "description": "Keyword like 'tech', 'sports', 'jazz'.",
                    },
                },
                "required": ["city", "country"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_save_preferences",
            "description": (
                "Save or update user preferences "
                "(home city/country, interests)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "home_city": {"type": "string"},
                    "home_country": {"type": "string"},
                    "passions": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_get_preferences",
            "description": "Fetch stored preferences for personalization.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tool_subscribe_digest",
            "description": "Subscribe the user to periodic event digests.",
            "parameters": {
                "type": "object",
                "properties": {
                    "frequency": {
                        "type": "string",
                        "enum": ["daily", "weekly"],
                        "default": "weekly",
                    }
                },
            },
        },
    },
]


# -------------------------------------------------
# Shared state for last tool call
# -------------------------------------------------

_LAST_TOOL_RESULT: Dict[str, Any] = {}


def tool_search_events(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Wrapper around search_events_sync used by the LLM tool call.

    Always returns a dict with at least:
      - count: int
      - items: list[dict]
      - error: optional error string (only on failure)
    """
    global _LAST_TOOL_RESULT

    city = (args.get("city") or "").strip()
    country = (args.get("country") or "").strip().upper()[:2]
    days_ahead = int(args.get("days_ahead", 30) or 30)
    start_in_days = int(args.get("start_in_days", 0) or 0)
    include_mock = bool(args.get("include_mock", True))
    query = args.get("query")

    try:
        data = search_events_sync(
            city=city,
            country=country,
            days_ahead=days_ahead,
            start_in_days=start_in_days,
            include_mock=include_mock,
            query=query,
        )

        # Normalize shape for the agent + callers
        items = data.get("items") or []
        count = int(data.get("count") or data.get("total") or len(items))

        result = {
            "count": count,
            "items": items,
            "debug": {
                "city": city,
                "country": country,
                "days_ahead": days_ahead,
                "start_in_days": start_in_days,
                "include_mock": include_mock,
                "query": query,
            },
        }

        try:
            storage.log_event_search(user_id, result["debug"], count=count)
        except Exception:
            pass

        _LAST_TOOL_RESULT = result
        return result

    except Exception as exc:
        result = {
            "count": 0,
            "items": [],
            "error": f"search failed: {exc!r}",
            "debug": {
                "city": city,
                "country": country,
                "days_ahead": days_ahead,
                "start_in_days": start_in_days,
                "include_mock": include_mock,
                "query": query,
            },
        }
        _LAST_TOOL_RESULT = result
        return result


def tool_save_preferences(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    city = args.get("city") or args.get("home_city")
    country = args.get("country") or args.get("home_country")

    profile = {
        "user_id": user_id,
        "username": args.get("username") or "demo",
        "city": city,
        "country": _coerce_country(country) or "LT",
        "home_city": city,
        "home_country": _coerce_country(country) or "LT",
        "passions": _normalize_passions(args.get("passions")),
        "days_ahead": int(args.get("days_ahead") or 120),
        "start_in_days": int(args.get("start_in_days") or 0),
        "keywords": args.get("keywords"),
    }

    try:
        if hasattr(storage, "upsert_profile"):
            saved = storage.upsert_profile(profile)
            return {"ok": True, "profile": saved or profile}

        storage.save_preferences(
            user_id=user_id,
            home_city=profile["city"],
            home_country=profile["country"],
            passions=profile["passions"],
        )
        return {"ok": True, "profile": profile}

    except Exception as exc:
        return {"ok": False, "error": str(exc), "profile": profile}


def tool_get_preferences(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    prefs = storage.get_preferences(user_id) or {}
    return {"preferences": prefs}


def tool_subscribe_digest(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    freq = args.get("frequency", "weekly")
    storage.upsert_subscription(user_id, frequency=freq)
    return {"ok": True, "frequency": freq}


TOOL_MAP = {
    "tool_search_events": tool_search_events,
    "tool_save_preferences": tool_save_preferences,
    "tool_get_preferences": tool_get_preferences,
    "tool_subscribe_digest": tool_subscribe_digest,
}


# -------------------------------------------------
# Agent loop
# -------------------------------------------------


class AgentTurn(BaseModel):
    reply: str
    used_tools: List[str] = []
    last_tool_result: Optional[Dict[str, Any]] = None


def _safe_json_loads(s: Optional[str]) -> Dict[str, Any]:
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {}

def _coerce_country(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().upper()[:2]

    if isinstance(value, dict):
        for key in ("code", "alpha2", "alpha_2", "countryCode"):
            v = value.get(key)
            if v:
                return str(v).strip().upper()[:2]

        name = value.get("name")
        if name:
            return str(name).strip().upper()[:2]

    return ""


def _normalize_passions(value: Any) -> List[str]:
    if value is None:
        return []

    if isinstance(value, str):
        return [p.strip() for p in value.split(",") if p.strip()]

    if isinstance(value, list):
        return [str(p).strip() for p in value if str(p).strip()]

    return []


def _load_profile_context(user_id: str) -> Dict[str, Any]:
    """
    Load profile/preferences from storage while supporting both old and new storage shapes.
    """
    try:
        if hasattr(storage, "get_profile"):
            prof = storage.get_profile(user_id) or {}
            if isinstance(prof, dict):
                return prof
    except Exception:
        pass

    try:
        if hasattr(storage, "get_preferences"):
            prefs = storage.get_preferences(user_id) or {}
            if isinstance(prefs, dict):
                return prefs
    except Exception:
        pass

    return {}


def _build_profile_context(
    *,
    user_id: str,
    username: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    days_ahead: Optional[int] = None,
    start_in_days: Optional[int] = None,
    keywords: Optional[str] = None,
    passions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    stored = _load_profile_context(user_id)

    final = {
        "user_id": user_id,
        "username": username or stored.get("username") or "demo",
        "city": city or stored.get("city") or stored.get("home_city") or "",
        "country": country or stored.get("country") or stored.get("home_country") or "LT",
        "days_ahead": days_ahead if days_ahead is not None else stored.get("days_ahead", 120),
        "start_in_days": start_in_days if start_in_days is not None else stored.get("start_in_days", 0),
        "keywords": keywords if keywords is not None else stored.get("keywords"),
        "passions": passions if passions is not None else stored.get("passions", []),
    }

    final["city"] = str(final["city"] or "").strip()
    final["country"] = _coerce_country(final["country"]) or "LT"

    try:
        final["days_ahead"] = int(final["days_ahead"] or 120)
    except Exception:
        final["days_ahead"] = 120

    try:
        final["start_in_days"] = int(final["start_in_days"] or 0)
    except Exception:
        final["start_in_days"] = 0

    final["passions"] = _normalize_passions(final["passions"])

    kw = final.get("keywords")
    final["keywords"] = str(kw).strip() if kw else None

    return final


def _format_events_fallback(items: List[Dict[str, Any]], city: str) -> str:
    if not items:
        return (
            f"I couldn't find matching events for {city or 'your city'} yet. "
            "Try widening your search window or using a broader keyword."
        )

    lines = [f"Here are a few events I found for {city or 'your city'}:"]

    for ev in items[:5]:
        title = ev.get("title") or "Untitled event"
        venue = ev.get("venue_name") or "Venue TBA"
        start = ev.get("start_time") or "Date TBA"
        url = ev.get("url")

        line = f"- {title} — {venue}, {start}"
        if url:
            line += f"\n  {url}"

        lines.append(line)

    return "\n".join(lines)

def run_agent(
    user_id: str,
    message: str,
    *,
    model: str = "gpt-4o-mini",
    username: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    days_ahead: Optional[int] = None,
    start_in_days: Optional[int] = None,
    keywords: Optional[str] = None,
    passions: Optional[List[str]] = None,
) -> AgentTurn:
    """
    Core agent loop powered by LangGraph's ReAct agent.

    Supports both:
    - old callers: run_agent(user_id, message)
    - FastHTML/router callers with profile context:
      run_agent(user_id, message, city=..., country=..., passions=...)
    """
    global _LAST_TOOL_RESULT
    _LAST_TOOL_RESULT = {}

    msg_text = (message or "").strip()

    if not msg_text:
        return AgentTurn(
            ok=False,
            answer="Please type a message first.",
            reply="Please type a message first.",
            error="empty_message",
        )

    profile = _build_profile_context(
        user_id=user_id,
        username=username,
        city=city,
        country=country,
        days_ahead=days_ahead,
        start_in_days=start_in_days,
        keywords=keywords,
        passions=passions,
    )

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": (
                "Current user profile context:\n"
                f"- user_id: {profile['user_id']}\n"
                f"- username: {profile['username']}\n"
                f"- city: {profile['city'] or 'missing'}\n"
                f"- country: {profile['country'] or 'missing'}\n"
                f"- days_ahead: {profile['days_ahead']}\n"
                f"- start_in_days: {profile['start_in_days']}\n"
                f"- keywords: {profile['keywords'] or 'none'}\n"
                f"- passions: {', '.join(profile['passions']) if profile['passions'] else 'none'}\n\n"
                "Use this context when calling tools. If the user asks for events "
                "and city/country are available, do not ask for location again."
            ),
        },
        {"role": "user", "content": msg_text},
    ]

    used_tools: List[str] = []

    # ---- LangGraph tool wrappers ----

    def search_events_tool(
        city: Optional[str] = None,
        country: Optional[str] = None,
        days_ahead: Optional[int] = None,
        start_in_days: Optional[int] = None,
        include_mock: bool = True,
        query: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Search events for a city/country with optional keyword filters."""
        args: Dict[str, Any] = {
            "city": city or profile["city"],
            "country": country or profile["country"],
            "days_ahead": days_ahead if days_ahead is not None else profile["days_ahead"],
            "start_in_days": start_in_days if start_in_days is not None else profile["start_in_days"],
            "include_mock": include_mock,
            "query": query or profile["keywords"],
        }
        result = tool_search_events(user_id, args)
        used_tools.append("tool_search_events")
        return result

    def save_preferences_tool(
        home_city: Optional[str] = None,
        home_country: Optional[str] = None,
        city: Optional[str] = None,
        country: Optional[str] = None,
        passions: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Save or update user preferences."""
        args: Dict[str, Any] = {
            "home_city": home_city or city,
            "home_country": home_country or country,
            "passions": passions,
        }
        result = tool_save_preferences(user_id, args)
        used_tools.append("tool_save_preferences")
        return result

    def get_preferences_tool() -> Dict[str, Any]:
        """Fetch stored preferences for personalization."""
        result = tool_get_preferences(user_id, {})
        used_tools.append("tool_get_preferences")
        return result

    def subscribe_digest_tool(
        frequency: str = "weekly",
    ) -> Dict[str, Any]:
        """Subscribe the user to periodic event digests."""
        result = tool_subscribe_digest(user_id, {"frequency": frequency})
        used_tools.append("tool_subscribe_digest")
        return result

    def rag_search_tool(
        query: str,
        city: Optional[str] = None,
        k: int = 5,
    ) -> Dict[str, Any]:
        """Look up background knowledge about cities, venues, or FAQs."""
        hits = rag.search_knowledge(query=query, city=city or profile["city"], k=k)
        used_tools.append("tool_rag_search")
        return {"hits": hits}

    tools = [
        search_events_tool,
        save_preferences_tool,
        get_preferences_tool,
        subscribe_digest_tool,
        rag_search_tool,
    ]

    try:
        llm = ChatOpenAI(model=model, temperature=0.4)

        graph = create_react_agent(
            model=llm,
            tools=tools,
            prompt=SYSTEM_PROMPT,
        )

        state = graph.invoke({"messages": messages})

    except Exception as exc:
        try:
            storage.log_agent_error(
                user_id,
                f"langgraph_agent_failed: {exc!r}",
            )
        except Exception:
            pass

        fallback_items: List[Dict[str, Any]] = []

        if profile["city"] and profile["country"]:
            fallback_result = tool_search_events(
                user_id,
                {
                    "city": profile["city"],
                    "country": profile["country"],
                    "days_ahead": profile["days_ahead"],
                    "start_in_days": profile["start_in_days"],
                    "include_mock": True,
                    "query": profile["keywords"],
                },
            )
            fallback_items = fallback_result.get("items") or []

        fallback_answer = _format_events_fallback(fallback_items, profile["city"])

        _LAST_TOOL_RESULT = {
            "error": f"langgraph_agent_failed: {exc!r}",
            "items": fallback_items,
        }

        return AgentTurn(
            ok=False,
            answer=fallback_answer,
            reply=fallback_answer,
            used_tools=used_tools + (["fallback_search"] if fallback_items else []),
            items=fallback_items[:10],
            last_tool_result=_LAST_TOOL_RESULT,
            error=f"langgraph_agent_failed: {exc!r}",
            debug={
                "profile_context": profile,
                "fallback": True,
            },
        )

    msgs = state.get("messages", [])

    if not msgs:
        reply_text = "I couldn't generate a response."
    else:
        last = msgs[-1]
        reply_text = getattr(last, "content", None)

        if reply_text is None and isinstance(last, dict):
            reply_text = last.get("content", "")

        reply_text = (reply_text or "").strip() or "I couldn't generate a response."

    last_result = _LAST_TOOL_RESULT or {}
    items = last_result.get("items") or []

    if not reply_text and items:
        reply_text = _format_events_fallback(items, profile["city"])

    return AgentTurn(
        ok=True,
        answer=reply_text,
        reply=reply_text,
        used_tools=used_tools,
        items=items[:10],
        last_tool_result=last_result or None,
        debug={
            "profile_context": profile,
            "last_tool_result": last_result,
        },
    )

    
def chat(
    *,
    user_id: str,
    message: str,
    username: str | None = None,
    city: str | None = None,
    country: str | None = None,
) -> dict:
    """
    Entry point used by routers/agent.py.

    Returns:
      {
        "ok": True,
        "answer": "<model reply>",
        "items": [...],          # events if tool_search_events was used
        "used_tools": [...],
        "debug": {...},          # last tool result, if any
      }
    """
    turn = run_agent(
        user_id=user_id,
        message=message,
        city=city,
        country=country,
    )

    last = turn.last_tool_result or {}
    items = last.get("items") or []

    return {
        "ok": True,
        "answer": turn.reply,
        "items": items,
        "used_tools": turn.used_tools,
        "debug": {
            "last_tool_result": last,
            "city": city,
            "country": country,
        },
    }
