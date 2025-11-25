import os
import time
from typing import Dict, Any, List, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import streamlit as st

# =========================
# Config
# =========================
API = os.getenv("SOCIALITE_API",
                "https://socialite-7wkx.onrender.com").rstrip("/")

st.set_page_config(page_title="Socialite", page_icon="🎟️", layout="wide")
st.title("Socialite")
st.caption(f"API: `{API}`")

# Session defaults
if "user_id" not in st.session_state:
    st.session_state.user_id = "demo-user"
if "username" not in st.session_state:
    st.session_state.username = "demo"

# =========================
# HTTP helpers (with retries + sidebar diagnostics)
# =========================
_session = requests.Session()
_retry = Retry(
    total=3, connect=3, read=3, backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
    respect_retry_after_header=True,
)
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://", HTTPAdapter(max_retries=_retry))


def _req_json(method: str, path: str, *, timeout: int = 20, **kwargs) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    url = f"{API}{path}"
    t0 = time.time()
    try:
        r = _session.request(method, url, timeout=timeout, **kwargs)
        elapsed = round((time.time() - t0) * 1000)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        elapsed = round((time.time() - t0) * 1000)
        return {"ok": False, "error": str(e), "debug": {"url": url, "elapsed_ms": elapsed}}


def _get(path: str, **params) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    return _req_json("GET", path, params=params)


def _post(path: str, payload: Dict[str, Any], *, timeout: int = 30) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    return _req_json("POST", path, timeout=timeout, json=payload)


def _delete(path: str) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    return _req_json("DELETE", path)

# =========================
# Profile helpers
# =========================


def load_profile(uid: str) -> Dict[str, Any]:
    res = _get(f"/profile/{uid}")
    if isinstance(res, dict) and res.get("profile"):
        return res["profile"]
    return {"user_id": uid, "username": st.session_state.username}


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


def search_from_profile(p: Dict[str, Any], include_mock: bool) -> Dict[str, Any]:
    city = (p.get("city") or "").strip().title()
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

    # Use no-retry for heavy search endpoints
    result = _get_noretry("/events/search", timeout=60, **params)

    if not isinstance(result, dict):
        return {
            "count": 0,
            "items": [],
            "debug": {"reason": "invalid_response", "sent_params": params},
        }

    items = result.get("items") or []
    normalized_count = int(result.get(
        "count") or result.get("total") or len(items))
    result["count"] = normalized_count

    dbg = result.get("debug") or {}
    dbg["sent_params"] = params
    result["debug"] = dbg
    return result


def _get_noretry(path: str, *, timeout: int = 60, **params) -> Dict[str, Any]:
    """Direct GET without retry logic for heavy endpoints."""
    url = f"{API}{path}"
    t0 = time.time()
    try:
        r = requests.get(url, params=params, timeout=timeout)
        elapsed = round((time.time() - t0) * 1000)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        elapsed = round((time.time() - t0) * 1000)
        return {"ok": False, "error": str(e), "debug": {"url": url, "elapsed_ms": elapsed}}

# =========================
# UI components
# =========================


def event_card(e: Dict[str, Any], key: str, user_id: str):
    with st.container():
        title = e.get("title") or "Untitled Event"
        st.markdown(f"### {title}")

        chips = []
        if e.get("venue_name"):
            chips.append(f"📍 {e['venue_name']}")
        place = ", ".join([p for p in [e.get("city"), e.get("country")] if p])
        if place:
            chips.append(place)
        if e.get("start_time"):
            chips.append(f"🕐 {e['start_time']}")
        if e.get("category"):
            chips.append(f"🏷️ {e['category']}")
        if chips:
            st.caption(" • ".join(chips))

        desc = e.get("description")
        if desc and desc != "Event":
            st.text(desc[:200] + ("..." if len(desc) > 200 else ""))

        if e.get("image_url"):
            try:
                st.image(e["image_url"], use_column_width=True)
            except Exception:
                pass

        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            if e.get("url"):
                st.markdown(f"[🔗 View Details]({e['url']})")
        with c2:
            if st.button("💾 Save", key=f"save_{key}"):
                r = _post("/saved", {"user_id": user_id, "event": e})
                if r.get("ok"):
                    st.success("Saved!")
                else:
                    st.error("Save failed")
        with c3:
            if e.get("min_price") is not None:
                currency = e.get("currency") or ""
                st.write(f"💰 From {e['min_price']} {currency}".strip())

        st.divider()


# =========================
# Main App
# =========================
# Sidebar API status
with st.sidebar.expander("API Status", expanded=False):
    st.caption(f"Base: `{API}`")
    ping_result = _get("/")
    if ping_result.get("ok"):
        st.success("Connected ✅")
    else:
        st.error("Connection failed")

    if st.button("Run search test"):
        demo = _get(
            "/events/search",
            city="Vilnius", country="LT",
            days_ahead=120, start_in_days=0,
            include_mock=False
        )
        st.json(demo)

tabs = st.tabs(["🏠 Discover", "💬 Chat", "⚙️ Settings"])

# ---------- SETTINGS ----------
with tabs[2]:
    st.header("⚙️ Settings")
    st.caption("Configure your preferences for personalized recommendations.")
    prof = load_profile(st.session_state.user_id)

    with st.form("settings_form"):
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Account")
            username = st.text_input("Username", value=prof.get(
                "username") or st.session_state.username)
            user_id = st.text_input("User ID", value=prof.get(
                "user_id") or st.session_state.user_id)
        with c2:
            st.subheader("Location")
            home_city = st.text_input(
                "Home City", value=prof.get("city") or "Vilnius")
            country_in = st.text_input(
                "Country (ISO-2)", value=(prof.get("country") or "LT"))
            country_iso2 = (country_in or "").strip().upper()[:2]

        c3, c4 = st.columns(2)
        with c3:
            st.subheader("Search Window")
            days_ahead = st.slider("Days ahead", 7, 365,
                                   int(prof.get("days_ahead") or 120))
            start_in_days = st.slider(
                "Start in (days)", 0, 60, int(prof.get("start_in_days") or 0))
        with c4:
            st.subheader("Interests")
            keywords = st.text_input(
                "Search keywords", value=prof.get("keywords") or "")
            passions_text = st.text_area(
                "Passions / interests", value=", ".join(prof.get("passions") or []))

        with st.expander("Advanced"):
            include_mock_flag = st.checkbox(
                "Include mock data (for testing)", value=False)

        if st.form_submit_button("💾 Save Settings", type="primary"):
            passions = [p.strip()
                        for p in passions_text.split(",") if p.strip()]
            payload = {
                "user_id": user_id.strip() or st.session_state.user_id,
                "username": username.strip() or st.session_state.username,
                "city": home_city.strip().title(),
                "country": country_iso2,
                "days_ahead": int(days_ahead),
                "start_in_days": int(start_in_days),
                "keywords": (keywords.strip() or None),
                "passions": passions,
            }
            r = save_profile(payload)
            if r.get("ok"):
                st.success("Saved ✅")
                st.session_state.user_id = payload["user_id"]
                st.session_state.username = payload["username"]
                st.rerun()
            else:
                st.error(f"Save failed: {r.get('error') or 'unknown error'}")

# ---------- DISCOVER ----------
with tabs[0]:
    st.header("🏠 Discover Events")
    prof = load_profile(st.session_state.user_id)

    left, right = st.columns([1, 3], gap="large")
    with left:
        st.subheader("🎛️ Controls")
        include_mock_feed = st.checkbox("Include test data", value=False)
        if st.button("🔄 Refresh", type="primary"):
            st.rerun()
        with st.expander("Search Parameters"):
            st.json({
                "city": prof.get("city") or "(unset)",
                "country": prof.get("country") or "(unset)",
                "days_ahead": prof.get("days_ahead", 120),
                "start_in_days": prof.get("start_in_days", 0),
                "keywords": prof.get("keywords") or "(none)",
            })

    with right:
        st.subheader("📅 Recommended for you")
        if not (prof.get("city") and prof.get("country")):
            st.warning(
                "Set your **Home City** and **Country** in Settings first.")
        else:
            with st.spinner("🔍 Finding events..."):
                res = search_from_profile(prof, include_mock_feed)

            items = list(res.get("items") or [])
            if not items:
                st.info(
                    "No events matched your Settings. Try widening the date window or clearing keywords.")
                if res.get("debug"):
                    with st.expander("Diagnostics"):
                        st.json(res["debug"])
            else:
                # Sort by passion relevance
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
                for i, ev in enumerate(items):
                    event_card(
                        ev, key=f"discover_{i}_{ev.get('title', '')[:24]}", user_id=st.session_state.user_id)

# ---------- CHAT TAB ----------
with tabs[1]:
    st.header("💬 Chat with Socialite")
    st.caption(
        "Ask me about events, get recommendations, or plan your activities!"
    )

    # Load profile for context (city / country / passions)
    profile = load_profile(st.session_state.user_id)

    message = st.text_input(
        "💭 What are you looking for?",
        placeholder="e.g., 'concerts this weekend in my city' or 'comedy shows next month'",
    )

    if st.button("📤 Send", type="primary") and message:
        # Payload for the backend agent
        chat_payload = {
            "user_id": st.session_state.user_id,
            "username": st.session_state.username,
            "message": message,
            "city": profile.get("city"),
            "country": profile.get("country"),
        }

        # ---- 1) Try agent with a shorter timeout ----
        with st.spinner("🤔 Thinking..."):
            # shorter timeout than default, so we don't hang for 60s
            response = _post("/agent/chat", chat_payload, timeout=20)

        if response.get("error"):
            # Agent call failed from the Streamlit side (timeout / network, etc.)
            st.warning(
                "The AI agent had trouble replying (network or timeout issue). "
                "Falling back to a direct event search instead."
            )

            # ---- 2) Fallback: call /events/search directly ----
            try:
                fallback_result = search_from_profile(profile, include_mock=False)
            except Exception as e:
                st.error(f"❌ Fallback search also failed: {e}")
            else:
                items = fallback_result.get("items", [])
                if not items:
                    st.info(
                        "I still couldn’t find any events. Try adjusting your settings or date range."
                    )
                else:
                    st.markdown("### 🎯 Events I could find right now")
                    for idx, event in enumerate(items[:10]):  # cap a bit for chat
                        event_card(
                            event,
                            key=f"chat_fallback_{idx}_{event.get('title', '')[:20]}",
                            user_id=st.session_state.user_id,
                        )

                    # Optional: show a tiny bit of debug so you know what's happening
                    with st.expander("🔧 Agent debug"):
                        st.json(
                            {
                                "agent_error": response.get("error"),
                                "agent_debug": response.get("debug"),
                                "fallback_used": True,
                            }
                        )

        else:
            # Agent call succeeded
            answer = response.get("answer") or "I'm not sure how to help with that."
            st.markdown(f"🤖 **Socialite**: {answer}")

            events = response.get("items") or []
            if events:
                st.markdown("### 🎯 Recommended Events")
                for idx, event in enumerate(events[:5]):  # Limit to 5 events
                    event_card(
                        event,
                        key=f"chat_{idx}_{event.get('title', '')[:20]}",
                        user_id=st.session_state.user_id,
                    )

            # Optional: expose agent debug info if you want to inspect tools, etc.
            debug = response.get("debug") or {}
            if debug:
                with st.expander("🔧 Agent debug"):
                    st.json(debug)


    # Subscription section
    st.divider()
    st.subheader("📬 Subscriptions")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("📅 Subscribe Weekly"):
            sub_payload = {
                "user_id": st.session_state.user_id,
                "city": profile.get("city"),
                "country": profile.get("country"),
                "cadence": "WEEKLY",
                "keywords": profile.get("passions") or [],
            }
            result = _post("/agent/subscribe", sub_payload)
            if result.get("ok"):
                st.success("✅ Subscribed!")
            else:
                st.info(
                    f"ℹ️ {result.get('hint', 'Subscription feature coming soon!')}")

    with col2:
        if st.button("📧 Get Latest Digest"):
            digest_result = _get(f"/agent/digest/{st.session_state.user_id}")
            digest = digest_result.get("digest", [])
            if digest:
                with st.expander("📰 Latest Digest", expanded=True):
                    for item in digest:
                        st.markdown(f"**{item.get('title', 'Event')}**")
                        if item.get("note"):
                            st.write(item["note"])
                        st.divider()
            else:
                st.info("📭 No digest available yet.")

# Footer
st.divider()
st.caption("🎟️ Socialite — Discover amazing events in your city!")
