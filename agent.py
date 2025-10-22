from __future__ import annotations
import os, json
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta

from openai import OpenAI
from pydantic import BaseModel

from aggregator import search_events
from services import storage

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """You are Socialite — a friendly, efficient AI agent that finds
and plans real-world events. You:
- ask quick clarifying questions when needed,
- use tools to search events (never guess),
- tailor suggestions to the user's saved city, country, passions and past likes,
- provide actionable plans (titles, venues, dates, links),
- keep replies concise and scannable with bullets.

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
                    "country": {"type": "string", "description": "ISO-2 country code"},
                    "days_ahead": {"type": "integer", "minimum": 1, "maximum": 365, "default": 30},
                    "start_in_days": {"type": "integer", "minimum": 0, "maximum": 365, "default": 0},
                    "include_mock": {"type": "boolean", "default": False},
                    "query": {"type": "string", "description": "Keyword like 'tech', 'sports', 'jazz'."}
                },
                "required": ["city", "country"]
            }
        }
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
                    "passions": {"type": "array", "items": {"type": "string"}}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_get_preferences",
            "description": "Fetch stored preferences for personalization.",
            "parameters": { "type": "object", "properties": {} }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_subscribe_digest",
            "description": "Subscribe the user to periodic event digests.",
            "parameters": {
                "type": "object",
                "properties": {
                    "frequency": {"type": "string", "enum": ["daily", "weekly"], "default": "weekly"}
                }
            }
        }
    }
]

# ---- Local tool dispatchers ----

def tool_search_events(user_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    data = search_events(
        city=args["city"],
        country=args["country"],
        days_ahead=int(args.get("days_ahead", 30)),
        start_in_days=int(args.get("start_in_days", 0)),
        include_mock=bool(args.get("include_mock", False)),
        query=args.get("query"),
    )

    storage.log_event_search(user_id, args, count=data.get("count", 0))
    return data

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

# ---- Agent loop ----

class AgentTurn(BaseModel):
    reply: str
    used_tools: List[str] = []

def run_agent(user_id: str, message: str, model: str = "gpt-4o-mini") -> AgentTurn:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": message},
    ]

    # 1st LLM call
    resp = _client.chat.completions.create(
        model=model,
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
        temperature=0.4,
    )

    used_tools: List[str] = []
    msg = resp.choices[0].message

    while getattr(msg, "tool_calls", None):
        for call in msg.tool_calls:
            name = call.function.name
            args = json.loads(call.function.arguments or "{}")
            fn = TOOL_MAP.get(name)
            if not fn:
                tool_result = {"error": f"Unknown tool {name}"}
            else:
                tool_result = fn(user_id, args)
                used_tools.append(name)

            # append tool result back into context
            messages.append({
                "role": "assistant",
                "tool_calls": [call]  # echo the call we just handled
            })
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "name": name,
                "content": json.dumps(tool_result),
            })

        resp = _client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.4,
        )
        msg = resp.choices[0].message

    reply_text = (msg.content or "").strip()
    return AgentTurn(reply=reply_text, used_tools=used_tools)
