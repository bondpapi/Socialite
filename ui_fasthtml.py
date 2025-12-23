from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from fasthtml.common import *

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------

API = os.getenv("SOCIALITE_API", "http://127.0.0.1:8001").rstrip("/")
DEFAULT_USER_ID = os.getenv("SOCIALITE_USER", "demo-user")
DEFAULT_USERNAME = os.getenv("SOCIALITE_USERNAME", "demo")

# HTTP session with retries (same spirit as Streamlit app)
_session = requests.Session()
_retry = Retry(
    total=3,
    connect=3,
    read=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
    respect_retry_after_header=True,
)
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://", HTTPAdapter(max_retries=_retry))


def _req_json(
    method: str,
    path: str,
    *,
    timeout: int = 20,
    **kwargs: Any,
) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    """Low-level helper that calls the API and returns JSON or an error dict."""
    url = f"{API}{path}"
    t0 = time.time()
    try:
        resp = _session.request(method, url, timeout=timeout, **kwargs)
        elapsed = round((time.time() - t0) * 1000)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        elapsed = round((time.time() - t0) * 1000)
        return {
            "ok": False,
            "error": str(e),
            "debug": {"url": url, "elapsed_ms": elapsed},
        }


def _get(path: str, *, timeout: int = 20, **params: Any) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    return _req_json("GET", path, timeout=timeout, params=params)


def _post(
    path: str,
    payload: Dict[str, Any],
    *,
    timeout: int = 30,
) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    return _req_json("POST", path, timeout=timeout, json=payload)


# -------------------------------------------------------------------
# API helpers (profile, search, status)
# -------------------------------------------------------------------

def ping_api() -> bool:
    res = _get("/")
    return isinstance(res, dict) and bool(res.get("ok"))


def load_profile(uid: str) -> Dict[str, Any]:
    res = _get(f"/profile/{uid}")
    if isinstance(res, dict) and res.get("profile"):
        return res["profile"]
    return {"user_id": uid, "username": DEFAULT_USERNAME}


def save_profile(p: Dict[str, Any]) -> Dict[str, Any]:
    res = _post("/profile", p)
    if isinstance(res, dict):
        return res
    return {"ok": False, "error": "Unexpected profile response"}


def _coerce_country(value: Any) -> str:
    """Convert various country formats to ISO-2 uppercase string."""
    if isinstance(value, str):
        return value.strip().upper()[:2]
    if isinstance(value, dict):
        for k in ("code", "alpha2", "alpha_2", "countryCode"):
            v = value.get(k)
            if v:
                return str(v).strip().upper()[:2]
        name = value.get("name")
        if name:
            return str(name).strip().upper()[:2]
    return ""


def search_from_profile(p: Dict[str, Any], include_mock: bool) -> Dict[str, Any]:
    city = (p.get("city") or "").strip()
    country = _coerce_country(p.get("country"))

    if not city or not country:
        return {
            "count": 0,
            "items": [],
            "debug": {
                "reason": "invalid_location",
                "city": city,
                "country_raw": p.get("country"),
                "country_coerced": country,
            },
        }

    days_ahead = int(p.get("days_ahead") or 120)
    start_in_days = int(p.get("start_in_days") or 0)

    params: Dict[str, Any] = {
        "city": city,
        "country": country,
        "days_ahead": days_ahead,
        "start_in_days": start_in_days,
        "include_mock": bool(include_mock),
        "limit": 20,
    }

    q = (p.get("keywords") or "").strip()
    if q:
        params["query"] = q

    # Slightly higher timeout for heavier search
    result_raw = _get("/events/search", timeout=60, **params)

    if not isinstance(result_raw, dict):
        return {
            "count": 0,
            "items": [],
            "debug": {"reason": "invalid_response", "sent_params": params},
        }

    items = result_raw.get("items") or []
    normalized_count = int(
        result_raw.get("count") or result_raw.get("total") or len(items)
    )
    result_raw["count"] = normalized_count

    dbg = result_raw.get("debug") or {}
    dbg["sent_params"] = params
    result_raw["debug"] = dbg
    return result_raw


# -------------------------------------------------------------------
# FastHTML app + layout
# -------------------------------------------------------------------

app, rt = fast_app(pico=True)  # PicoCSS + sensible defaults


def nav_bar(active: str) -> Any:
    def tab(label: str, href: str, key: str) -> Any:
        cls = "contrast" if active == key else ""
        return Li(A(label, href=href, cls=cls))

    return Nav(
        Ul(
            tab("Discover", "/discover", "discover"),
            tab("Chat", "/chat", "chat"),
            tab("Settings", "/settings", "settings"),
        ),
        cls="nav",
    )


def shell(active: str, content: Any) -> Any:
    ok = ping_api()
    status = Span(
        "Connected ✅" if ok else "Offline",
        cls=f"badge {'success' if ok else 'secondary'}",
    )

    header = Div(
        H1("Socialite"),
        P("Your AI event concierge", cls="text-muted"),
        status,
        cls="container flex items-center gap-3 py-2",
    )

    return Div(
        header,
        nav_bar(active),
        Main(content, cls="container"),
        Footer(
            Small("🎟️ Socialite — Discover amazing events in your city!"),
            cls="container mt-4",
        ),
    )


def event_card(e: Dict[str, Any]) -> Any:
    title = e.get("title") or "Untitled Event"
    venue = e.get("venue_name")
    place_bits = [p for p in [e.get("city"), e.get("country")] if p]
    place = ", ".join(place_bits) if place_bits else None
    start_time = e.get("start_time")
    category = e.get("category")
    desc = e.get("description")
    url = e.get("url")

    chips: List[str] = []
    if venue:
        chips.append(f"📍 {venue}")
    if place:
        chips.append(place)
    if start_time:
        chips.append(f"🕐 {start_time}")
    if category:
        chips.append(f"🏷️ {category}")
    chips_text = " • ".join(chips) if chips else ""

    return Article(
        H3(title),
        Small(chips_text) if chips_text else None,
        P(desc[:220] + ("…" if desc and len(desc) > 220 else "")) if desc else None,
        A("View details →", href=url, target="_blank") if url else None,
        cls="card",
    )


# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------

@rt("/")
def index() -> Any:
    # Just show the Discover page by default.
    return discover()


# -------------------- Discover -------------------- #

@rt("/discover")
def discover(include_mock: bool = False) -> Any:
    user_id = DEFAULT_USER_ID
    prof = load_profile(user_id)

    city = (prof.get("city") or "").strip()
    country = (prof.get("country") or "").strip()

    if not city or not country:
        body = Section(
            H2("🏠 Discover Events"),
            P(
                "Browse recommended events based on your profile. "
                "Tune your city, country and interests in Settings."
            ),
            H3("Set up your location"),
            P("I need your city and country to find events for you."),
            A("Go to Settings →", href="/settings", cls="contrast"),
        )
        return shell("discover", body)

    # We have a valid location, so run search
    search_res = search_from_profile(prof, include_mock=include_mock)
    items = list(search_res.get("items") or [])
    count = int(search_res.get("count") or len(items))

    # Sort a little using passions, similar to Streamlit version
    passions = {p.lower() for p in (prof.get("passions") or [])}

    def score(ev: Dict[str, Any]) -> int:
        t = (ev.get("title") or "").lower()
        c = (ev.get("category") or "").lower()
        s = 0
        for p in passions:
            if p in t:
                s += 3
            if p in c:
                s += 2
        return s

    items.sort(key=score, reverse=True)

    controls = Form(
        Fieldset(
            Legend("🎛️ Controls"),
            Label(
                Input(
                    type="checkbox",
                    name="include_mock",
                    value="true",
                    checked=include_mock,
                ),
                "Include test data",
            ),
            Button("Refresh", type="submit", cls="primary"),
        ),
        method="get",
        cls="mb-3",
    )

    if not items:
        events_block: Any = P(
            "No events matched your Settings. Try widening the date window "
            "or clearing keywords.",
            cls="text-muted",
        )
    else:
        cards = [event_card(ev) for ev in items]
        events_block = Div(
            P(f"Showing {len(items)} of {count} events found.", cls="text-muted"),
            *cards,
            cls="grid",
        )

    body = Section(
        H2("🏠 Discover Events"),
        P(
            "Browse recommended events based on your profile. "
            "Tune your city, country and interests in Settings."
        ),
        controls,
        H3("📅 Recommended for you"),
        events_block,
    )
    return shell("discover", body)


# -------------------- Chat -------------------- #

@rt("/chat")
def chat(message: Optional[str] = None) -> Any:
    """
    Simple GET-based chat:
    - First load: empty form
    - With ?message=...: calls /agent/chat and shows response
    """
    user_id = DEFAULT_USER_ID
    username = DEFAULT_USERNAME
    prof = load_profile(user_id)

    answer: Optional[str] = None
    events: List[Dict[str, Any]] = []
    notice: Optional[str] = None

    if message:
        payload = {
            "user_id": user_id,
            "username": username,
            "message": message,
            "city": prof.get("city"),
            "country": prof.get("country"),
        }

        resp = _post("/agent/chat", payload, timeout=30)

        # Handle network / error case with fallback search
        if isinstance(resp, dict) and resp.get("error"):
            notice = (
                "The AI agent had trouble replying (network or timeout issue). "
                "Showing a direct event search instead."
            )
            search_res = search_from_profile(prof, include_mock=False)
            events = list(search_res.get("items") or [])
        elif isinstance(resp, dict):
            answer = (
                resp.get("answer", "").strip()
                or "I'm not sure how to help with that."
            )
            events = list(resp.get("items") or [])

    form = Form(
        Fieldset(
            Legend("💬 Chat with Socialite"),
            P(
                "Ask me about events, get recommendations, or plan your activities!"
            ),
            Input(
                type="text",
                name="message",
                placeholder="e.g., 'concerts this weekend in my city'",
                value=message or "",
            ),
            Button("Send", type="submit", cls="primary"),
        ),
        method="get",
        cls="mb-3",
    )

    blocks: List[Any] = [form]

    if answer:
        blocks.append(
            Article(
                H3("🤖 Socialite"),
                Div(answer, cls="prose"),
                cls="card",
            )
        )

    if notice and not answer:
        blocks.append(P(notice, cls="text-muted"))

    if events:
        blocks.append(H3("🎯 Recommended Events"))
        blocks.extend(event_card(ev) for ev in events[:5])

    body = Section(*blocks)
    return shell("chat", body)


# -------------------- Settings -------------------- #

@rt("/settings")
def settings(
    user_id: str = DEFAULT_USER_ID,
    username: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    days_ahead: Optional[int] = None,
    start_in_days: Optional[int] = None,
    keywords: Optional[str] = None,
    passions: Optional[str] = None,
    save: Optional[str] = None,
) -> Any:
    """
    GET-only settings page:
    - First load: pre-filled with current profile
    - Submitting the form uses ?save=1 and updates profile via API
    """
    prof = load_profile(DEFAULT_USER_ID)

    # Initial values from profile
    username_val = username or prof.get("username") or DEFAULT_USERNAME
    user_id_val = user_id or prof.get("user_id") or DEFAULT_USER_ID
    city_val = city or prof.get("city") or ""
    country_val = (country or prof.get("country") or "LT")[:2]
    days_ahead_val = int(days_ahead or prof.get("days_ahead") or 120)
    start_in_days_val = int(start_in_days or prof.get("start_in_days") or 0)
    keywords_val = keywords or prof.get("keywords") or ""
    passions_val = passions or ", ".join(prof.get("passions") or [])

    saved: bool = False
    error_msg: Optional[str] = None

    if save == "1":
        passions_list = [
            p.strip() for p in (passions_val or "").split(",") if p.strip()
        ]
        payload = {
            "user_id": user_id_val.strip() or DEFAULT_USER_ID,
            "username": username_val.strip() or DEFAULT_USERNAME,
            "city": city_val.strip(),
            "country": country_val.strip().upper()[:2],
            "days_ahead": int(days_ahead_val),
            "start_in_days": int(start_in_days_val),
            "keywords": keywords_val.strip() or None,
            "passions": passions_list,
        }
        res = save_profile(payload)
        if res.get("ok"):
            saved = True
        else:
            error_msg = res.get("error") or "Failed to save settings."

    alerts: List[Any] = []
    if saved:
        alerts.append(P("Saved ✅", cls="text-success"))
    if error_msg:
        alerts.append(P(f"Save failed: {error_msg}", cls="text-danger"))

    form = Form(
        Input(type="hidden", name="save", value="1"),
        Fieldset(
            Legend("Account"),
            Label("Username", Input(name="username", value=username_val)),
            Label("User ID", Input(name="user_id", value=user_id_val)),
        ),
        Fieldset(
            Legend("Location"),
            Label("Home City", Input(name="city", value=city_val)),
            Label(
                "Country (ISO-2)",
                Input(name="country", value=country_val),
            ),
        ),
        Fieldset(
            Legend("Search Window"),
            Label(
                "Days ahead",
                Input(
                    type="number",
                    name="days_ahead",
                    value=str(days_ahead_val),
                    min="7",
                    max="365",
                ),
            ),
            Label(
                "Start in (days)",
                Input(
                    type="number",
                    name="start_in_days",
                    value=str(start_in_days_val),
                    min="0",
                    max="60",
                ),
            ),
        ),
        Fieldset(
            Legend("Interests"),
            Label(
                "Search keywords",
                Input(name="keywords", value=keywords_val),
            ),
            Label(
                "Passions / interests (comma-separated)",
                Textarea(name="passions", value=passions_val, rows=3),
            ),
        ),
        Button("Save Settings", type="submit", cls="primary"),
        method="get",
    )

    body = Section(
        H2("⚙️ Settings"),
        P("Configure your preferences for personalized recommendations."),
        *alerts,
        form,
    )
    return shell("settings", body)


# -------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------

if __name__ == "__main__":
    # Run with:  python ui_fasthtml.py
    serve()
