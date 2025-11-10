import os
from typing import Dict, Any, List

import requests
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
# HTTP helpers
# =========================


def _get(path: str, **params) -> Dict[str, Any] | List[Dict[str, Any]]:
    try:
        r = requests.get(f"{API}{path}", params=params, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _post(path: str, payload: Dict[str, Any], *, timeout: int = 30) -> Dict[str, Any]:
    try:
        r = requests.post(f"{API}{path}", json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _delete(path: str) -> Dict[str, Any]:
    try:
        r = requests.delete(f"{API}{path}", timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

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


def search_from_profile(p: Dict[str, Any], include_mock: bool) -> Dict[str, Any]:
    city = (p.get("city") or "").strip().title()
    country = (p.get("country") or "").strip().upper()[:2]

    if not city or not country:
        return {
            "count": 0,
            "items": [],
            "debug": {"reason": "missing_city_or_country", "city": city, "country": country},
        }

    days_ahead = int(p.get("days_ahead") or 120)
    start_in_days = int(p.get("start_in_days") or 0)
    query = (p.get("keywords") or None)

    return _get(
        "/events/search",
        city=city, country=country,
        days_ahead=days_ahead, start_in_days=start_in_days,
        include_mock=bool(include_mock), query=query
    ) or {"count": 0, "items": [], "debug": {"errors": ["no response"]}}

# =========================
# UI bits
# =========================


def event_card(e: Dict[str, Any], key: str, user_id: str):
    with st.container():
        st.markdown(f"### {e.get('title') or 'Untitled'}")
        chips = []
        if e.get("venue_name"):
            chips.append(e["venue_name"])
        if e.get("city"):
            chips.append(e["city"])
        if e.get("country"):
            chips.append(e["country"])
        if e.get("start_time"):
            chips.append(e["start_time"])
        if e.get("category"):
            chips.append(f"• {e['category']}")
        st.caption(" · ".join(chips))

        c1, c2, c3 = st.columns(3)
        with c1:
            if e.get("url"):
                st.markdown(f"[Open]({e['url']})")
        with c2:
            if st.button("Save", key=f"save_{key}"):
                _post("/saved", {"user_id": user_id, "event": e})
                st.success("Saved ✅")
        with c3:
            mp = e.get("min_price")
            if mp is not None:
                st.write(f"From {mp} {e.get('currency') or ''}".strip())


# =========================
# Tabs
# =========================
tab_discover, tab_chat, tab_settings = st.tabs(
    ["Discover", "Chat 🤖", "Settings"])

# ---------- SETTINGS ----------
with tab_settings:
    st.header("Settings")
    st.caption("These preferences power Discover and personalize Chat.")

    prof = load_profile(st.session_state.user_id)

    col1, col2 = st.columns(2)
    with col1:
        username = st.text_input("Username", prof.get(
            "username") or st.session_state.username)
        user_id = st.text_input("User ID", prof.get(
            "user_id") or st.session_state.user_id)
        city = st.text_input("Home city", prof.get("city") or "Vilnius")
        country = st.text_input(
            "Country (ISO-2)", (prof.get("country") or "LT")[:2])
    with col2:
        days_ahead = st.number_input(
            "Days ahead", 1, 365, int(prof.get("days_ahead") or 120))
        start_in_days = st.number_input(
            "Start in (days)", 0, 365, int(prof.get("start_in_days") or 0))
        keywords = st.text_input(
            "Keywords (comma-sep)", prof.get("keywords") or "")
        passions_raw = st.text_input(
            "Passions / interests (comma-sep)", ", ".join(prof.get("passions") or []))
        include_mock = st.checkbox("Include mock data (for testing)", False)

    if st.button("Save settings", type="primary"):
        passions = [p.strip() for p in passions_raw.split(",") if p.strip()]
        payload = {
            "user_id": user_id,
            "username": username,
            "city": city.strip().title(),
            "country": country.strip().upper()[:2],
            "days_ahead": int(days_ahead),
            "start_in_days": int(start_in_days),
            "keywords": keywords.strip() or None,
            "passions": passions,
        }
        res = save_profile(payload)
        if res.get("ok"):
            st.success("Saved ✅")
            st.session_state.user_id = user_id
            st.session_state.username = username
        else:
            st.error(f"Save failed: {res.get('error') or 'unknown error'}")

# ---------- DISCOVER ----------
with tab_discover:
    left, right = st.columns([1, 3], gap="large")

    with left:
        st.subheader("Feed controls")
        st.caption("Uses Settings → city/country/keywords/date window.")
        include_mock_feed = st.checkbox("Include mock in feed", value=False)
        if st.button("Refresh now"):
            st.rerun()

    with right:
        st.subheader("Recommended for you")
        prof = load_profile(st.session_state.user_id)

        if not (prof.get("city") and prof.get("country")):
            st.info(
                "Set your **Home city** and **Country** in Settings, then click Refresh.")
        else:
            res = search_from_profile(prof, include_mock_feed)

            if res.get("count", 0) == 0:
                st.info(
                    "No events matched your Settings. Try widening the date window or clearing keywords.")
                dbg = res.get("debug")
                if dbg:
                    with st.expander("Diagnostics"):
                        st.json(dbg)
            else:
                items: List[Dict[str, Any]] = res.get("items", [])
                passions = {p.lower() for p in (prof.get("passions") or [])}

                def score(ev: Dict[str, Any]) -> int:
                    t = (ev.get("title") or "").lower()
                    c = (ev.get("category") or "").lower()
                    s = 0
                    for p in passions:
                        if p in t:
                            s += 2
                        if p in c:
                            s += 1
                    return -s

                items.sort(key=score)
                for i, ev in enumerate(items):
                    event_card(
                        ev, key=f"{i}_{ev.get('title', '')}", user_id=st.session_state.user_id)

    st.divider()
    st.caption("Tip: update Settings and click Refresh.")


# ---------- CHAT ----------
with tab_chat:
    st.header("Chat with Socialite 🤖")
    st.caption("Ask for plans or specifics; the agent reads your Settings.")

    message = st.text_input(
        "Message", placeholder="e.g., live music next weekend in my city")
    if st.button("Send", type="primary"):
        prof = load_profile(st.session_state.user_id)
        payload = {
            "user_id": st.session_state.user_id,
            "username": st.session_state.username,
            "message": message,
            "city": prof.get("city"),
            "country": prof.get("country"),
        }
        res = _post("/agent/chat", payload)
        if res.get("ok") is False and res.get("error"):
            st.error(f"Agent error: {res['error']}")
        else:
            st.write(res.get("answer") or res)

    st.divider()
    st.subheader("Subscriptions")
    colA, colB = st.columns(2)
    with colA:
        if st.button("Subscribe me weekly"):
            prof = load_profile(st.session_state.user_id)
            payload = {
                "user_id": st.session_state.user_id,
                "city": prof.get("city"),
                "country": prof.get("country"),
                "cadence": "WEEKLY",
                "keywords": prof.get("passions") or [],
            }
            res = _post("/agent/subscribe", payload)
            if res.get("ok"):
                st.success("Subscribed ✅")
            else:
                st.warning(res.get("hint") or res.get("error")
                           or "Subscription not configured")
    with colB:
        if st.button("Fetch latest digest now"):
            res = _get(f"/agent/digest/{st.session_state.user_id}")
            digest = res.get("digest") if isinstance(res, dict) else None
            if digest:
                with st.expander("Latest digest"):
                    for card in digest:
                        st.markdown(f"**{card.get('title', '(untitled)')}**")
                        if card.get("note"):
                            st.write(card["note"])
                        st.divider()
            else:
                st.info("No digest available yet.")
