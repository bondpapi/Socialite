import os
import time
from typing import Any, Dict, List, Union

import requests
from fasthtml.common import *  # type: ignore
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# Config

API_BASE = os.getenv(
    "SOCIALITE_API", "https://socialite-7wkx.onrender.com"
).rstrip("/")


WEB_USER_ID = os.getenv("SOCIALITE_WEB_USER_ID", "web-demo-user")
WEB_USERNAME = os.getenv("SOCIALITE_WEB_USERNAME", "web-user")

app, rt = fast_app()


# HTTP helpers

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
    method: str, path: str, *, timeout: int = 20, **kwargs
) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    url = f"{API_BASE}{path}"
    t0 = time.time()
    try:
        r = _session.request(method, url, timeout=timeout, **kwargs)
        elapsed = round((time.time() - t0) * 1000)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        elapsed = round((time.time() - t0) * 1000)
        return {
            "ok": False,
            "error": str(e),
            "debug": {"url": url, "elapsed_ms": elapsed},
        }


def _get(path: str, **params):
    return _req_json("GET", path, params=params)


def _post(path: str, payload: Dict[str, Any], *, timeout: int = 30):
    return _req_json("POST", path, timeout=timeout, json=payload)


def _delete(path: str):
    return _req_json("DELETE", path)


def _get_direct(path: str, *, timeout: int = 60, **params) -> Dict[str, Any]:
    """Direct GET without retry logic for heavy endpoints."""
    url = f"{API_BASE}{path}"
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e), "debug": {"url": url}}


# Profile + search helpers (ported from Streamlit app)

def load_profile(uid: str) -> Dict[str, Any]:
    res = _get(f"/profile/{uid}")
    if isinstance(res, dict) and res.get("profile"):
        return res["profile"]
    return {"user_id": uid, "username": WEB_USERNAME}


def save_profile(p: Dict[str, Any]) -> Dict[str, Any]:
    return _post("/profile", p)


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
        p: Dict[str, Any], include_mock: bool) -> Dict[str, Any]:
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

    days_ahead = int(p.get("days_ahead") or 90)
    start_in_days = int(p.get("start_in_days") or 0)

    params = {
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

    result = _get_direct("/events/search", timeout=60, **params)

    if not isinstance(result, dict):
        return {
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
    return result


# UI helpers


def nav(active: str = "discover"):
    def link(label: str, href: str, key: str):
        cls = "contrast" if key == active else ""
        return A(label, href=href, cls=cls)

    return Nav(
        Ul(
            Li(link("Discover", "/discover", "discover")),
            Li(link("Chat", "/chat", "chat")),
            Li(link("Settings", "/settings", "settings")),
            cls="flex gap-2",
        ),
        cls="ml-auto",
    )


def api_status_badge() -> Any:
    ping = _get("/")
    if isinstance(ping, dict) and ping.get("ok"):
        return Span("Connected ✅", cls="badge success")
    return Span("API Error ❌", cls="badge danger")


def event_card(e: Dict[str, Any], key: str, user_id: str) -> Any:
    title = e.get("title") or "Untitled Event"
    venue = e.get("venue_name")
    place = ", ".join([p for p in [e.get("city"), e.get("country")] if p])
    when = e.get("start_time") or e.get("local_date")
    category = e.get("category")
    desc = e.get("description")
    img = e.get("image_url")
    url = e.get("url")
    price = e.get("min_price")
    currency = e.get("currency") or ""
    source = e.get("source") or e.get("provider") or ""

    chips = []
    if venue:
        chips.append(f"📍 {venue}")
    if place:
        chips.append(place)
    if when:
        chips.append(f"🕐 {when}")
    if category:
        chips.append(f"🏷️ {category}")
    if source:
        chips.append(f"🔗 {source}")

    header = Div(
        H3(title),
        P(" • ".join(chips)) if chips else "",
        cls="card-header",
    )

    body: List[Any] = []
    if desc and desc != "Event" and len(desc.strip()) > 3:
        short = desc[:200] + ("…" if len(desc) > 200 else "")
        body.append(P(short))

    if img:
        body.append(Img(src=img, cls="w-100 rounded"))

    buttons: List[Any] = []
    if url:
        buttons.append(
            A("View details", href=url, target="_blank", cls="button")
        )

    if price is not None:
        buttons.append(
            Span(f"From {price} {currency}".strip(), cls="text-muted")
        )

    footer = Div(
        *buttons, cls="flex gap-2 items-center justify-between mt-2"
    )

    return Article(
        header,
        Div(*body, cls="card-body"),
        footer,
        cls="card",
    )


def page_layout(active: str, *sections: Any):
    """
    Shared layout wrapper:
    - Header with logo, tagline, nav, API status
    - Main content
    - Footer
    """
    header = Header(
        Div(
            Span("🎟️", cls="logo text-xxl"),
            Div(
                H2("Socialite"),
                P("Your AI event concierge", cls="text-muted"),
                cls="title",
            ),
            cls="flex items-center gap-3",
        ),
        Div(
            api_status_badge(),
            cls="ml-auto",
        ),
        nav(active),
        cls="container flex items-center gap-3 py-2",
    )

    footer = Footer(
        Div(
            Small(
                "🎟️ Socialite — Discover amazing events in your city!"
            ),
            cls="text-muted",
        ),
        cls="container py-3",
    )

    return Titled(
        "Socialite",
        header,
        Main(*sections, cls="container my-3"),
        footer,
    )


# Routes


@rt("/")
def root():
    # Redirect root to Discover
    return Redirect("/discover")


# DISCOVER


@rt("/discover")
def discover(include_mock: str = "0"):

    include_bool = include_mock == "1"
    prof = load_profile(WEB_USER_ID)

    hero = Section(
        H1("🏠 Discover Events"),
        P(
            "Browse recommended events based on your profile. "
            "Tune your city, country and interests in Settings."
        ),
        cls="card",
    )

    sections: List[Any] = [hero]

    if not (prof.get("city") and prof.get("country")):
        sections.append(
            Section(
                H3("Set up your location"),
                P("I need your city and country to find events for you."),
                A("Go to Settings →", href="/settings", cls="button"),
                cls="card warning",
            )
        )
        return page_layout("discover", *sections)

    # Controls + params grid
    controls = Form(
        Fieldset(
            Legend("🎛️ Controls"),
            Label("Include test data?"),
            Select(
                Option("No", value="0", selected=not include_bool),
                Option("Yes", value="1", selected=include_bool),
                name="include_mock",
            ),
        ),
        Button("🔄 Refresh", type="submit"),
        method="get",
        cls="card",
    )

    params_card = Div(
        H3("Current search window"),
        Ul(
            Li(Strong("City: "), Span(prof.get("city") or "(unset)")),
            Li(
                Strong("Country: "),
                Span(prof.get("country") or "(unset)")
            ),
            Li(
                Strong("Days ahead: "),
                Span(str(prof.get("days_ahead") or 120))
            ),
            Li(
                Strong("Start in: "),
                Span(f"{prof.get('start_in_days', 0)} days")
            ),
            Li(
                Strong("Keywords: "),
                Span(prof.get("keywords") or "(none)"),
            ),
        ),
        cls="card",
    )

    sections.append(
        Section(
            Div(
                params_card,
                controls,
                cls="grid",
            )
        )
    )

    # Run search
    res = search_from_profile(prof, include_bool)
    items = list(res.get("items") or [])

    if not items:
        sections.append(
            Section(
                H2("No events matched your Settings"),
                P(
                    "Try widening the date range or clearing keywords. "
                    "You can adjust this in Settings."
                ),
                cls="card info",
            )
        )
        if res.get("debug"):
            sections.append(
                Section(
                    Details(
                        Summary("Diagnostics (for debugging)"),
                        Pre(str(res["debug"])),
                    ),
                    cls="card",
                )
            )
    else:
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

        cards = [
            event_card(ev, f"discover_{i}", WEB_USER_ID)
            for i, ev in enumerate(items)
        ]

        sections.append(
            Section(
                H2("📅 Recommended for you"),
                Div(*cards, cls="grid"),
            )
        )

    return page_layout("discover", *sections)


# CHAT


@rt("/chat")
def chat(message: str = ""):

    prof = load_profile(WEB_USER_ID)
    answer = None
    events: List[Dict[str, Any]] = []
    warning_msg = None
    error_msg = None

    if message:
        chat_payload = {
            "user_id": WEB_USER_ID,
            "username": WEB_USERNAME,
            "message": message,
            "city": prof.get("city"),
            "country": prof.get("country"),
        }

        response = _post("/agent/chat", chat_payload, timeout=25)

        if isinstance(response, dict) and response.get("error"):
            warning_msg = (
                "The AI agent had trouble replying "
                "(network or timeout issue). "
                "Falling back to a direct event search instead."
            )
            search_result = search_from_profile(prof, include_mock=False)
            events = search_result.get("items", [])
            if not events:
                error_msg = (
                    "I couldn't find any events. "
                    "Try adjusting your settings or date range."
                )
        elif isinstance(response, dict):
            answer = (
                response.get("answer", "").strip()
                or "I'm not sure how to help with that."
            )
            events = response.get("items", [])
        else:
            error_msg = "Unexpected response format from agent."

    # Chat input
    chat_form = Form(
        Fieldset(
            Legend("What are you looking for?"),
            TextArea(
                message,
                name="message",
                placeholder=(
                    "e.g., 'concerts this weekend in my city' or "
                    "'comedy shows next month'"
                ),
                rows=3,
            ),
        ),
        Button("📤 Send", type="submit"),
        method="get",
        cls="card",
    )

    left_column: List[Any] = [
        H1("💬 Chat with Socialite"),
        P(
            "Ask me about events, get recommendations, "
            "or plan your activities!"
        ),
        chat_form,
    ]

    if warning_msg:
        left_column.append(Section(P(warning_msg), cls="card warning"))

    if error_msg and not events and not answer:
        left_column.append(Section(P(error_msg), cls="card info"))

    if answer:
        left_column.append(
            Section(
                H3("🤖 Socialite"),
                P(answer),
                cls="card",
            )
        )

    # Events on the right
    right_column: List[Any] = []
    if events:
        cards = [
            event_card(ev, f"chat_{i}", WEB_USER_ID)
            for i, ev in enumerate(events[:8])
        ]
        right_column.append(
            Section(
                H2("🎯 Recommended Events"),
                Div(*cards, cls="grid"),
            )
        )

    # Subscriptions area
    subs = Section(
        H2("📬 Subscriptions"),
        P("Subscribe for weekly digests or pull your latest digest."),
        Div(
            Form(
                Button("📅 Subscribe Weekly", type="submit"),
                Input(type="hidden", name="action", value="subscribe"),
                method="post",
                action="/subscriptions",
                cls="inline",
            ),
            Form(
                Button("📧 Get Latest Digest", type="submit"),
                Input(type="hidden", name="action", value="digest"),
                method="post",
                action="/subscriptions",
                cls="inline",
            ),
            cls="flex gap-2",
        ),
        cls="card",
    )

    layout_grid = Section(
        Div(
            Div(*left_column, cls="flex flex-col gap-3"),
            Div(*right_column, cls="flex flex-col gap-3"),
            cls="grid",
        ),
    )

    return page_layout("chat", layout_grid, subs)


# SETTINGS


@rt("/settings")
def settings(
    username: str = "",
    city: str = "",
    country: str = "",
    days_ahead: int = 120,
    start_in_days: int = 0,
    keywords: str = "",
    passions: str = "",
    save: str = "",
):

    prof = load_profile(WEB_USER_ID)

    if not save:
        username = username or prof.get("username") or WEB_USERNAME
        city = city or prof.get("city") or "Vilnius"
        country = country or prof.get("country") or "LT"
        days_ahead = int(prof.get("days_ahead") or 120)
        start_in_days = int(prof.get("start_in_days") or 0)
        keywords = keywords or prof.get("keywords") or ""
        passions = passions or ", ".join(prof.get("passions") or [])
        saved = None
    else:
        passions_list = [p.strip() for p in passions.split(",") if p.strip()]
        country_iso2 = (country or "").strip().upper()[:2]

        payload = {
            "user_id": WEB_USER_ID,
            "username": username.strip() or WEB_USERNAME,
            "city": city.strip(),
            "country": country_iso2,
            "days_ahead": int(days_ahead),
            "start_in_days": int(start_in_days),
            "keywords": keywords.strip() or None,
            "passions": passions_list,
        }

        r = save_profile(payload)
        saved = bool(isinstance(r, dict) and r.get("ok"))

    sections: List[Any] = [
        Section(
            H1("⚙️ Settings"),
            P("Configure your preferences for personalized recommendations."),
            cls="card",
        )
    ]

    if save:
        if saved:
            sections.append(Section(P("Saved ✅"), cls="card success"))
        else:
            sections.append(Section(P("Save failed"), cls="card warning"))

    form = Form(
        Div(
            Fieldset(
                Legend("Account"),
                Label("Username"),
                Input(value=username, name="username"),
            ),
            Fieldset(
                Legend("Location"),
                Label("Home City"),
                Input(value=city, name="city"),
                Label("Country (ISO-2)"),
                Input(value=country, name="country"),
            ),
            cls="grid",
        ),
        Div(
            Fieldset(
                Legend("Search Window"),
                Label("Days ahead"),
                Input(
                    type="number", value=str(days_ahead), name="days_ahead"
                ),
                Label("Start in (days)"),
                Input(
                    type="number",
                    value=str(start_in_days),
                    name="start_in_days",
                ),
            ),
            Fieldset(
                Legend("Interests"),
                Label("Search keywords"),
                Input(value=keywords, name="keywords"),
                Label("Passions / interests (comma separated)"),
                TextArea(passions, name="passions", rows=3),
            ),
            cls="grid",
        ),
        Input(type="hidden", name="save", value="1"),
        Button("💾 Save Settings", type="submit"),
        method="get",
        cls="card",
    )

    sections.append(form)
    return page_layout("settings", *sections)


# SAVE EVENT ENDPOINT (best-effort wrapper)


@rt("/save-event", methods=["POST"])
def save_event(user_id: str = "", event_key: str = ""):
    # In a fuller version you'd re-fetch the event by key.
    # For now this is a no-op acknowledgement.
    return Redirect("/discover")


# Entrypoint


if __name__ == "__main__":
    serve()
