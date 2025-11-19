import os
import time
from typing import Dict, Any, List, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import streamlit as st

# Config

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

# HTTP helpers (with retries + sidebar diagnostics)
_session = requests.Session()
_retry = Retry(
    total=3, connect=3, read=3, backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
    respect_retry_after_header=True,
)
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://", HTTPAdapter(max_retries=_retry))

# single expander instance used by helper to avoid creating
# a new expander on every request
SIDEBAR_EXPANDER = st.sidebar.expander("API Status", expanded=False)


def _req_json(method: str, path: str, *, timeout: int = 20, **kwargs) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    url = f"{API}{path}"
    t0 = time.time()
    try:
        r = _session.request(method, url, timeout=timeout, **kwargs)
        elapsed = round((time.time() - t0) * 1000)
        # update expander with a brief status line
        SIDEBAR_EXPANDER.caption(
            f"{method} {path} → {r.status_code} ({elapsed}ms)")
        r.raise_for_status()
        return r.json()
    except Exception as e:
        elapsed = round((time.time() - t0) * 1000)
        SIDEBAR_EXPANDER.error(
            f"{method} {path} failed ({elapsed}ms): {str(e)[:120]}")
        return {"ok": False, "error": str(e), "debug": {"url": url, "elapsed_ms": elapsed}}


def _get(path: str, **params) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    return _req_json("GET", path, params=params)


def _post(path: str, payload: Dict[str, Any], *, timeout: int = 30) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    return _req_json("POST", path, timeout=timeout, json=payload)


def _delete(path: str) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    return _req_json("DELETE", path)


# Quick root ping (shows up in the sidebar expander above)
ping_result = _get("/")
SIDEBAR_EXPANDER.caption(f"Base: `{API}`")
if isinstance(ping_result, dict) and ping_result.get("ok"):
    SIDEBAR_EXPANDER.success("Connected ✅")
else:
    SIDEBAR_EXPANDER.error("Connection failed")

# Profile helpers


def load_profile(uid: str) -> Dict[str, Any]:
    res = _get(f"/profile/{uid}")
    # expected shape: {"ok": True, "profile": {...}}
    if isinstance(res, dict) and res.get("profile"):
        return res["profile"]
    # graceful default
    return {"user_id": uid, "username": st.session_state.username}


def save_profile(p: Dict[str, Any]) -> Dict[str, Any]:
    # API expects POST /profile (body contains user_id)
    return _post("/profile", p)


def _coerce_country(value) -> str:
    """
    Accepts 'LT', 'lt', {'code':'LT'}, {'countryCode':'LT'}, {'name':'Lithuania'}, etc.
    Returns a best-effort ISO-2 uppercase string or ''.
    """
    if isinstance(value, str):
        return value.strip().upper()[:2]
    if isinstance(value, dict):
        for k in ("code", "alpha2", "alpha_2", "countryCode"):
            v = value.get(k)
            if v:
                return str(v).strip().upper()[:2]
        # last resort: take the first two letters of the name
        name = value.get("name")
        if name:
            return str(name).strip().upper()[:2]
    return ""


def search_from_profile(p: Dict[str, Any], include_mock: bool) -> Dict[str, Any]:
    city = (p.get("city") or "").strip().title()
    country = _coerce_country(p.get("country"))

    # only block when we truly have nothing usable
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

    # slightly smaller default window helps keep responses snappy
    days_ahead = int(p.get("days_ahead") or 90)
    start_in_days = int(p.get("start_in_days") or 0)

    params: Dict[str, Any] = {
        "city": city,
        "country": country,
        "days_ahead": days_ahead,
        "start_in_days": start_in_days,
        "include_mock": bool(include_mock),
        "limit": 20,  # keep payloads small to avoid UI timeouts
    }
    q = (p.get("keywords") or "").strip()
    if q:
        params["query"] = q

    # ---- single-shot GET (no retry) with longer timeout ----
    url = f"{API}/events/search"
    t0 = time.time()
    try:
        r = requests.get(url, params=params, timeout=60)
        elapsed_ms = int((time.time() - t0) * 1000)
        r.raise_for_status()
        result = r.json()
    except Exception as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        return {
            "count": 0,
            "items": [],
            "debug": {
                "reason": "no_response",
                "error": str(e),
                "sent_params": params,
                "url": url,
                "elapsed_ms": elapsed_ms,
            },
        }
    # --------------------------------------------------------

    if not isinstance(result, dict):
        return {
            "count": 0,
            "items": [],
            "debug": {"reason": "no_response", "sent_params": params, "url": url},
        }

    # normalize count so the UI logic is consistent
    items = result.get("items") or []
    normalized_count = int(result.get("count") or result.get("total") or len(items))
    result["count"] = normalized_count

    # include what we actually asked the API for easier debugging
    dbg = result.get("debug") or {}
    dbg["sent_params"] = params
    result["debug"] = dbg
    return result


# --- no-retry helper for heavy endpoints ---
def _get_noretry(path: str, *, timeout: int = 60, **params) -> Dict[str, Any]:
    url = f"{API}{path}"
    t0 = time.time()
    try:
        # use a fresh requests call (bypasses the Session with retries)
        r = requests.get(url, params=params, timeout=timeout)
        elapsed = round((time.time() - t0) * 1000)
        if st.sidebar:
            st.sidebar.caption(f"GET (no-retry) {path} → {r.status_code} ({elapsed}ms)")
        r.raise_for_status()
        return r.json()
    except Exception as e:
        elapsed = round((time.time() - t0) * 1000)
        if st.sidebar:
            st.sidebar.error(f"GET (no-retry) {path} failed ({elapsed}ms): {str(e)[:80]}")
        return {"ok": False, "error": str(e), "debug": {"url": url, "elapsed_ms": elapsed}}


# UI components


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
                st.success("Saved!") if r.get(
                    "ok") else st.error("Save failed")
        with c3:
            if e.get("min_price") is not None:
                st.write(
                    f"💰 From {e['min_price']} {(e.get('currency') or '').strip()}")

        st.divider()

# Main App


with st.sidebar.expander("API Status", expanded=False):
    st.caption(f"Base: `{API}`")
    ping_result = _get("/")
    st.success("Connected ✅" if ping_result.get("ok") else "Connection failed")

    if st.button("Run search smoke test"):
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
            # coerce after widget returns to avoid funky first-render issues
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

        submitted = st.form_submit_button("💾 Save Settings", type="primary")
        if submitted:
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

            items: List[Dict[str, Any]] = list(res.get("items") or [])
            if not items:
                st.info(
                    "No events matched your Settings. Try widening the date window or clearing keywords.")
                if res.get("debug"):
                    with st.expander("Diagnostics"):
                        st.json(res["debug"])
            else:
                # sort by simple passion relevance
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

# ---------- CHAT ----------
with tabs[1]:
    st.header("💬 Chat with Socialite")
    prof = load_profile(st.session_state.user_id)

    msg = st.text_input("💭 What are you looking for?",
                        placeholder="e.g., 'concerts this weekend in my city'")
    if st.button("📤 Send", type="primary") and msg:
        payload = {
            "user_id": st.session_state.user_id,
            "username": st.session_state.username,
            "message": msg,
            "city": prof.get("city"),
            "country": prof.get("country"),
        }
        with st.spinner("🤔 Thinking..."):
            res = _post("/agent/chat", payload, timeout=60)

        if res.get("error"):
            st.error(f"❌ Chat failed: {res['error']}")
        else:
            st.markdown(
                f"**Socialite**: {res.get('answer') or 'I couldn’t find anything for that.'}")
            picks = res.get("items") or []
            if picks:
                st.markdown("### 🎯 Picks")
                for i, ev in enumerate(picks[:5]):
                    event_card(
                        ev, key=f"chat_{i}_{ev.get('title', '')[:24]}", user_id=st.session_state.user_id)

# Footer
st.divider()
st.caption("🎟️ Socialite — Discover amazing events in your city!")
