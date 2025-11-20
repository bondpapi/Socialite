from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from openai import OpenAI
from pydantic import BaseModel

from services.aggregator import search_events_sync
from services import storage

_client = OpenAI(timeout=15, max_retries=1)

SYSTEM_PROMPT = """You are Socialite — a friendly, efficient AI agent that finds
and plans real-world events. You:
- ask quick clarifying questions when needed,
- use tools to search events (never guess),
- tailor suggestions to the user's saved city, country, passions and past likes,
- provide actionable plans (titles, venues, dates, links),
- keep replies concise and scannable with bullets.

When you use the event search tool:
- summarize key options in natural language,
- and rely on the tool's `items` list for concrete event details
  (titles, venues, dates, links, prices).

If the user asks for a digest or notifications, call the subscribe tool.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "tool_search_events",
            "description": "Search events for a city/country with optional keyword filters.",
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
            "description": "Save or update user preferences (home city/country, interests).",
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

        storage.log_event_search(user_id, result["debug"], count=count)
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
    Core agent loop. Optionally receives city/country hints for better prompting.
    """
    global _LAST_TOOL_RESULT
    _LAST_TOOL_RESULT = {}

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]

    # If we have location hints, share them with the model
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

    resp = _client.chat.completions.create(
        model=model,
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
        temperature=0.4,
    )

    used_tools: List[str] = []
    msg = resp.choices[0].message

    # Tool-call loop
    while getattr(msg, "tool_calls", None):
        for call in msg.tool_calls:
            name = call.function.name
            args = _safe_json_loads(call.function.arguments)
            fn = TOOL_MAP.get(name)

            if not fn:
                tool_result = {"error": f"Unknown tool {name}"}
            else:
                tool_result = fn(user_id, args)
                used_tools.append(name)

            # tool call + tool result messages
            messages.append(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(args),
                            },
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": name,
                    "content": json.dumps(tool_result),
                }
            )

        resp = _client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.4,
        )
        msg = resp.choices[0].message

    reply_text = (msg.content or "").strip()
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
