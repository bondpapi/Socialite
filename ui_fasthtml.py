from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from fasthtml.common import (
    A,
    Article,
    Body,
    Button,
    Div,
    Footer,
    Form,
    H1,
    H2,
    H3,
    Head,
    Html,
    Input,
    Label,
    Link,
    Main,
    Meta,
    Nav,
    P,
    Script,
    Span,
    Strong,
    Title,
    fast_app,
    serve,
)


API = os.getenv(
    "SOCIALITE_API", "https://socialite-7wkx.onrender.com"
).rstrip("/")

DEFAULT_USER_ID = "demo-user"
DEFAULT_USERNAME = "demo"

# Simple requests session
_session = requests.Session()
_adapter = requests.adapters.HTTPAdapter(max_retries=3)
_session.mount("http://", _adapter)
_session.mount("https://", _adapter)


def _req_json(
    method: str, path: str, *, timeout: int = 20, **kwargs
) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    url = f"{API}{path}"
    t0 = time.time()
    try:
        r = _session.request(method, url, timeout=timeout, **kwargs)
        elapsed = round((time.time() - t0) * 1000)
        r.raise_for_status()
        data = r.json()
        # Normalise ok flag
        if isinstance(data, dict) and "ok" not in data:
            data.setdefault("ok", True)
        return data
    except Exception as e:
        elapsed = round((time.time() - t0) * 1000)
        return {
            "ok": False,
            "error": str(e),
            "debug": {"url": url, "elapsed_ms": elapsed},
        }


def _get(path: str, **params) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    return _req_json("GET", path, params=params)


def _post(
    path: str, payload: Dict[str, Any], *, timeout: int = 30
) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    return _req_json("POST", path, timeout=timeout, json=payload)


def check_api_status() -> bool:
    res = _get("/")
    return isinstance(res, dict) and bool(res.get("ok"))


def load_profile(user_id: str) -> Tuple[Dict[str, Any], bool]:
    """Return (profile, api_ok). Guarantees at least user_id + username."""
    ok = check_api_status()
    base = {"user_id": user_id, "username": "demo"}

    if not ok:
        return base, False

    res = _get(f"/profile/{user_id}")
    if isinstance(res, dict) and res.get("profile"):
        prof = {**base, **res["profile"]}
    else:
        prof = base

    return prof, True


def save_profile(
    profile: Dict[str, Any]
) -> Tuple[Dict[str, Any], bool, str]:
    """Try to upsert profile, return (profile, success, error_message)."""
    res = _post("/profile", profile)
    if not isinstance(res, dict):
        return profile, False, "Invalid response from API"

    if res.get("ok"):
        return res.get("profile", profile), True, ""
    else:
        return profile, False, str(res.get("error") or "Unknown API error")


def _coerce_country(value) -> str:
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


def search_from_profile(
    p: Dict[str, Any], include_mock: bool
) -> Dict[str, Any]:
    city = (p.get("city") or "").strip()
    country = _coerce_country(p.get("country"))

    if not city or not country:
        return {
            "ok": False,
            "count": 0,
            "items": [],
            "debug": {
                "reason": "invalid_location",
                "city": city,
                "country_raw": p.get("country"),
                "country_coerced": country,
            },
        }

    days_ahead = int(p.get("days_ahead") or 90)
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

    result = _get("/events/search", **params)

    if not isinstance(result, dict):
        return {
            "ok": False,
            "count": 0,
            "items": [],
            "debug": {"reason": "invalid_response", "sent_params": params},
        }

    items = result.get("items") or []
    normalized_count = int(
        result.get("count") or result.get("total") or len(items)
    )
    result["count"] = normalized_count

    dbg = result.get("debug") or {}
    dbg["sent_params"] = params
    result["debug"] = dbg
    result.setdefault("ok", True)
    return result


def call_agent_chat(
    *,
    user_id: str,
    username: str,
    message: str,
    city: str | None,
    country: str | None,
) -> Dict[str, Any]:
    payload = {
        "user_id": user_id,
        "username": username,
        "message": message,
        "city": city,
        "country": country,
    }
    res = _post("/agent/chat", payload, timeout=25)
    if isinstance(res, dict):
        return res
    return {"ok": False, "error": "Unexpected response from /agent/chat"}


def status_badge(online: bool):
    if online:
        return Span("Connected ✅", cls="badge success")
    return Span("Offline", cls="badge")


def nav_bar(active: str):
    def link(label: str, href: str, key: str):
        cls = "contrast" if key == active else ""
        return A(label, href=href, cls=cls)

    discover_cls = "me-2" + (" contrast" if active == "discover" else "")
    chat_cls = "me-2" + (" contrast" if active == "chat" else "")
    settings_cls = " contrast" if active == "settings" else ""

    return Nav(
        A("Discover", href="/discover", cls=discover_cls),
        A("Chat", href="/chat", cls=chat_cls),
        A("Settings", href="/settings", cls=settings_cls),
        cls="flex gap-3 my-3",
    )


def event_chip_row(e: Dict[str, Any]):
    chips: List[str] = []
    if e.get("venue_name"):
        chips.append(f"📍 {e['venue_name']}")
    place = ", ".join([p for p in [e.get("city"), e.get("country")] if p])
    if place:
        chips.append(place)
    if e.get("start_time"):
        chips.append(f"🕐 {e['start_time']}")
    if e.get("category"):
        chips.append(f"🏷️ {e['category']}")
    if not chips:
        return None
    return P(" • ".join(chips), cls="text-small secondary")


def event_card(e: Dict[str, Any]):
    title = e.get("title") or "Untitled Event"
    desc = e.get("description")
    if desc and desc != "Event":
        desc = desc.strip()
        if len(desc) > 220:
            desc = desc[:220] + "…"
    else:
        desc = None

    chips = event_chip_row(e)
    more = (
        A("🔗 View details", href=e["url"], target="_blank")
        if e.get("url")
        else None
    )

    price_part = None
    price = e.get("min_price")
    if price is not None:
        currency = e.get("currency") or ""
        price_part = P(f"💰 From {price} {currency}".strip(), cls="text-small")

    children = [H3(title)]
    if chips:
        children.append(chips)
    if desc:
        children.append(P(desc))
    if more or price_part:
        row = Div(cls="flex gap-3 mt-1")
        if more:
            row.add(more)
        if price_part:
            row.add(price_part)
        children.append(row)

    return Article(*children, cls="card")


def page_shell(active: str, online: bool, main_content):
    """Shared layout for all pages."""
    return (
        "<!doctype html>",
        Html(
            Head(
                Title("Socialite"),
                Meta(charset="utf-8"),
                Meta(
                    name="viewport",
                    content=(
                        "width=device-width, initial-scale=1, "
                        "viewport-fit=cover"
                    ),
                ),
                # htmx + Surreal + Pico CSS
                Script(
                    src="https://cdn.jsdelivr.net/npm/htmx.org@2.0.7"
                    "/dist/htmx.js"
                ),
                Script(
                    src="https://cdn.jsdelivr.net/gh/answerdotai/surreal@"
                    "main/surreal.js"
                ),
                Link(
                    rel="stylesheet",
                    href=(
                        "https://cdn.jsdelivr.net/npm/@picocss/pico@latest/"
                        "css/pico.min.css"
                    ),
                ),
                # Simple dark background
                Script(
                    """
                    document.documentElement.setAttribute('data-theme', 'dark');
                    """
                ),
            ),
            Body(
                Main(
                    Div(
                        H1("Socialite"),
                        P("Your AI event concierge", cls="text-small"),
                        status_badge(online),
                        nav_bar(active),
                        main_content,
                        cls="container",
                    )
                ),
                Footer(
                    P(
                        "🎟️ Socialite — Discover amazing events in "
                        "your city!",
                        cls="text-small",
                    ),
                    cls="container mt-4 mb-2",
                ),
            ),
        ),
    )


app, rt = fast_app()


@rt("/")
def get_root():
    # Redirect root to /discover
    # FastHTML doesn't have a dedicated Redirect component; easiest is meta refresh.
    online = check_api_status()
    main = Div(
        P("Redirecting to Discover…"),
        Script("window.location.href = '/discover';"),
    )
    return page_shell("discover", online, main)


@rt("/discover")
def get_discover():
    online = check_api_status()
    profile = load_profile(DEFAULT_USER_ID) if online else {
        "user_id": DEFAULT_USER_ID,
        "username": DEFAULT_USERNAME,
    }

    if not online:
        main = Div(
            H2("🏠 Discover Events"),
            P(
                "The backend API seems offline. Start the API server "
                "or check your SOCIALITE_API setting."
            ),
        )
        return page_shell("discover", online, main)

    city = (profile.get("city") or "").strip()
    country = (profile.get("country") or "").strip()

    if not city or not country:
        main = Div(
            H2("🏠 Discover Events"),
            P(
                "Browse recommended events based on your profile. "
                "Tune your city, country and interests in Settings."
            ),
            H3("Set up your location"),
            P("I need your city and country to find events for you."),
            A("Go to Settings →", href="/settings", cls="contrast"),
        )
        return page_shell("discover", online, main)

    res = search_from_profile(profile, include_mock=False)
    items = list(res.get("items") or [])
    error = res.get("error") if not res.get("ok") else None

    cards: List[Any] = []

    if error:
        cards.append(
            P(
                f"⚠️ There was a problem searching for events: {error}",
                cls="secondary",
            )
        )
    elif not items:
        cards.append(
            P(
                "No events matched your current settings. Try widening the "
                "date window or clearing your keywords in Settings.",
                cls="secondary",
            )
        )
    else:
        passions = {p.lower() for p in (profile.get("passions") or [])}

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
        cards.extend(event_card(ev) for ev in items)

    main = Div(
        H2("🏠 Discover Events"),
        P(
            "Browse recommended events based on your profile. "
            "Tune your city, country and interests in Settings.",
            cls="secondary",
        ),
        *cards,
    )
    return page_shell("discover", online, main)


def chat_body(
    profile: Dict[str, Any],
    online: bool,
    message: str = "",
    answer: str | None = None,
    events: Optional[List[Dict[str, Any]]] = None,
    warning: str | None = None,
):
    events = events or []

    form = Form(
        Input(
            name="message",
            type="text",
            placeholder="e.g., 'concerts this weekend in my city'",
            value=message,
        ),
        Button("Send", type="submit", cls="contrast"),
        method="post",
        action="/chat",
    )

    blocks: List[Any] = [
        H2("💬 Chat with Socialite"),
        P(
            "Ask me about events, get recommendations, "
            "or plan your activities!"
        ),
        form,
    ]

    if not online:
        blocks.append(
            P(
                "The backend API seems offline, so I can't answer "
                "right now. Try again once the API is running.",
                cls="secondary mt-3",
            )
        )

    if warning:
        blocks.append(P(f"⚠️ {warning}", cls="secondary mt-3"))

    if answer:
        blocks.append(
            Div(
                P("🤖 Socialite:", cls="text-small secondary"),
                P(answer),
                cls="mt-3",
            )
        )

    if events:
        blocks.append(H3("🎯 Recommended Events"))
        for ev in events[:5]:
            blocks.append(event_card(ev))

    return Div(*blocks)


@rt("/chat")
def get_chat():
    online = check_api_status()
    profile = load_profile(DEFAULT_USER_ID) if online else {
        "user_id": DEFAULT_USER_ID,
        "username": DEFAULT_USERNAME,
    }
    main = chat_body(profile, online)
    return page_shell("chat", online, main)


@rt("/chat")
def post(message: str):
    # Handle chat form submission
    online = check_api_status()
    profile = load_profile(DEFAULT_USER_ID) if online else {
        "user_id": DEFAULT_USER_ID,
        "username": DEFAULT_USERNAME,
    }

    answer = None
    events: List[Dict[str, Any]] = []
    warning = None

    if not online:
        warning = (
            "The backend API seems offline, so I can't reach the AI agent right now."
        )
    else:
        msg = (message or "").strip()
        if not msg:
            warning = "Please type a message before sending."
        else:
            city = profile.get("city")
            country = profile.get("country")
            res = call_agent_chat(
                user_id=profile.get("user_id") or DEFAULT_USER_ID,
                username=profile.get("username") or DEFAULT_USERNAME,
                message=msg,
                city=city,
                country=country,
            )

            if not res.get("ok") and res.get("error"):
                warning = (
                    "The AI agent had trouble replying (network or "
                    "timeout issue). Falling back to a direct event "
                    "search instead."
                )
                if city and country:
                    search_res = search_from_profile(profile, include_mock=False)
                    if isinstance(search_res, dict):
                        events = list(search_res.get("items") or [])[:5]
            else:
                answer = (res.get("answer") or "").strip() or (
                    "I'm not sure how to help with that."
                )
                events = list(res.get("items") or [])[:5]

    main = chat_body(profile, online, message=message, answer=answer, events=events, warning=warning)
    return page_shell("chat", online, main)


def settings_form(
    profile: Dict[str, Any],
    online: bool,
    saved: bool = False,
    error: str | None = None,
):
    username = profile.get("username") or DEFAULT_USERNAME
    user_id = profile.get("user_id") or DEFAULT_USER_ID
    home_city = profile.get("city") or ""
    country = profile.get("country") or "LT"
    days_ahead = int(profile.get("days_ahead") or 120)
    start_in_days = int(profile.get("start_in_days") or 0)
    keywords = profile.get("keywords") or ""
    passions_text = ", ".join(profile.get("passions") or [])

    msgs: List[Any] = []
    if saved:
        msgs.append(P("✅ Settings saved.", cls="text-small success"))
    if error:
        msgs.append(P(f"⚠️ {error}", cls="text-small secondary"))

    form = Form(
        H3("Account"),
        Label(
            "Username",
            Input(name="username", value=username),
        ),
        Label(
            "User ID",
            Input(name="user_id", value=user_id),
        ),
        H3("Location"),
        Label(
            "Home City",
            Input(name="home_city", value=home_city),
        ),
        Label(
            "Country (ISO-2)",
            Input(name="country_iso2", value=country),
        ),
        H3("Search Window"),
        Label(
            "Days ahead",
            Input(
                name="days_ahead",
                type="number",
                min="7",
                max="365",
                value=str(days_ahead),
            ),
        ),
        Label(
            "Start in (days)",
            Input(
                name="start_in_days",
                type="number",
                min="0",
                max="60",
                value=str(start_in_days),
            ),
        ),
        H3("Interests"),
        Label(
            "Search keywords",
            Input(name="keywords", value=keywords),
        ),
        Label(
            "Passions / interests (comma-separated)",
            Input(name="passions_text", value=passions_text),
        ),
        Button("💾 Save Settings", type="submit", cls="contrast mt-2"),
        method="post",
        action="/settings",
    )

    return Div(
        H2("⚙️ Settings"),
        P(
            "Configure your preferences for personalized "
            "recommendations."
        ),
        *msgs,
        form,
    )


@rt("/settings")
def get_settings():
    online = check_api_status()
    profile = load_profile(DEFAULT_USER_ID) if online else {
        "user_id": DEFAULT_USER_ID,
        "username": DEFAULT_USERNAME,
    }
    main = settings_form(profile, online)
    return page_shell("settings", online, main)


@rt("/settings")
def post(
    username: str,
    user_id: str,
    home_city: str,
    country_iso2: str,
    days_ahead: int,
    start_in_days: int,
    keywords: str = "",
    passions_text: str = "",
):
    online = check_api_status()
    profile = {
        "user_id": user_id.strip() or DEFAULT_USER_ID,
        "username": username.strip() or DEFAULT_USERNAME,
        "city": home_city.strip(),
        "country": (country_iso2 or "").strip().upper()[:2],
        "days_ahead": int(days_ahead),
        "start_in_days": int(start_in_days),
        "keywords": (keywords or "").strip() or None,
        "passions": [
            p.strip()
            for p in (passions_text or "").split(",")
            if p.strip()
        ],
    }

    if not online:
        error_msg = "API appears offline; could not save."
        main = settings_form(profile, online, saved=False, error=error_msg)
        return page_shell("settings", online, main)

    res = save_profile(profile)
    error = None
    saved = False
    if not res.get("ok"):
        error = res.get("error") or "Unknown error"
    else:
        saved = True

    main = settings_form(profile, online, saved=saved, error=error)
    return page_shell("settings", online, main)

if __name__ == "__main__":
    # Run with: python ui_fasthtml.py
    serve()

