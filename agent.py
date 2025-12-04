from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

from openai import APIError, APITimeoutError, OpenAI, RateLimitError
from pydantic import BaseModel

from services import storage
from services.aggregator import search_events_sync

_client = OpenAI(timeout=20, max_retries=1)

SYSTEM_PROMPT = (
    """You are Socialite — a friendly, efficient AI agent that finds
and plans real-world events. You:
- ask quick clarifying questions when needed,
- use tools to search events (never guess),
- tailor suggestions to the user's saved city, country, passions and """
    """past likes,
- provide actionable plans (titles, venues, dates, links),
- keep replies concise and scannable with bullets.

When you use the event search tool:
- summarize key options in natural language,
- and rely on the tool's `items` list for concrete event details
  (titles, venues, dates, links, prices).

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

        storage.log_event_search(
            user_id, result["debug"], count=count
        )
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
    storage.save_preferences(
        user_id=user_id,
        home_city=args.get("home_city"),
        home_country=args.get("home_country"),
        passions=args.get("passions"),
    )
    return {"ok": True}


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


def run_agent(
    user_id: str,
    message: str,
    *,
    model: str = "gpt-4o-mini",
    city: Optional[str] = None,
    country: Optional[str] = None,
) -> AgentTurn:
    """
    Core agent loop, now powered by LangGraph's ReAct agent.

    We:
    - build a LangGraph ReAct agent with per-request tools (bound to user_id)
    - invoke it with the conversation messages
    - keep track of used tools and last tool result via closures + existing tool_* functions
    """
    global _LAST_TOOL_RESULT
    _LAST_TOOL_RESULT = {}

    # Conversation messages (same structure you had before)
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]

    if city or country:
        loc_bits = []
        if city:
            loc_bits.append(f"city={city}")
        if country:
            loc_bits.append(f"country={country}")
        messages.append(
            {
                "role": "system",
                "content": f"User location context: {', '.join(loc_bits)}.",
            }
        )

    messages.append({"role": "user", "content": message})

    used_tools: List[str] = []

    # ---- LangGraph tool wrappers (capture user_id + used_tools) ----

    def search_events_tool(
        city: str,
        country: str,
        days_ahead: int = 30,
        start_in_days: int = 0,
        include_mock: bool = True,
        query: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Search events for a city/country with optional keyword filters."""
        args: Dict[str, Any] = {
            "city": city,
            "country": country,
            "days_ahead": days_ahead,
            "start_in_days": start_in_days,
            "include_mock": include_mock,
            "query": query,
        }
        result = tool_search_events(user_id, args)
        used_tools.append("tool_search_events")
        return result

    def save_preferences_tool(
        home_city: Optional[str] = None,
        home_country: Optional[str] = None,
        passions: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Save or update user preferences (home city/country, interests)."""
        args: Dict[str, Any] = {
            "home_city": home_city,
            "home_country": home_country,
            "passions": passions,
        }
        result = tool_save_preferences(user_id, args)
        used_tools.append("tool_save_preferences")
        return result

    def get_preferences_tool() -> Dict[str, Any]:
        """Fetch stored preferences for personalization."""
        args: Dict[str, Any] = {}
        result = tool_get_preferences(user_id, args)
        used_tools.append("tool_get_preferences")
        return result

    def subscribe_digest_tool(
        frequency: str = "weekly",
    ) -> Dict[str, Any]:
        """Subscribe the user to periodic event digests."""
        args: Dict[str, Any] = {"frequency": frequency}
        result = tool_subscribe_digest(user_id, args)
        used_tools.append("tool_subscribe_digest")
        return result

    tools = [
        search_events_tool,
        save_preferences_tool,
        get_preferences_tool,
        subscribe_digest_tool,
    ]

    # ---- Build LangGraph ReAct agent ----
    try:
        llm = ChatOpenAI(model=model, temperature=0.4)
        graph = create_react_agent(
            model=llm,
            tools=tools,
            prompt=SYSTEM_PROMPT,
        )

        # LangGraph expects {"messages": [...]} as input
        state = graph.invoke({"messages": messages})

    except Exception as exc:
        # Fallback behaviour if LangGraph/LLM fails
        try:
            storage.log_agent_error(
                user_id, f"langgraph_agent_failed: {exc!r}")
        except Exception:
            pass

        _LAST_TOOL_RESULT = {"error": f"langgraph_agent_failed: {exc!r}"}
        return AgentTurn(
            reply=(
                "Sorry, I had trouble talking to the AI model. "
                "Please try again in a bit or use the Discover tab."
            ),
            used_tools=used_tools,
            last_tool_result=_LAST_TOOL_RESULT,
        )

    # ---- Extract final reply from LangGraph state ----
    msgs = state.get("messages", [])
    if not msgs:
        reply_text = "I couldn't generate a response."
    else:
        last = msgs[-1]
        # last may be a LangChain message object or a plain dict
        reply_text = getattr(last, "content", None) or last.get(
            "content", "") or ""
        reply_text = reply_text.strip() or "I couldn't generate a response."

    return AgentTurn(
        reply=reply_text,
        used_tools=used_tools,
        last_tool_result=_LAST_TOOL_RESULT or None,
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
