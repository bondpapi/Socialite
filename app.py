import os
import time
from typing import Dict, Any, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import streamlit as st

# =========================
# Config
# =========================
API = os.getenv("SOCIALITE_API", "https://socialite-7wkx.onrender.com").rstrip("/")

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


def _req_json(method: str, path: str, *, timeout: int = 20, **kwargs):
    url = f"{API}{path}"
    t0 = time.time()
    try:
        r = _session.request(method, url, timeout=timeout, **kwargs)
        elapsed = round((time.time() - t0) * 1000)
        if st.sidebar:
            st.sidebar.caption(
                f"{method} {path} → {r.status_code} ({elapsed}ms)")
        r.raise_for_status()
        return r.json()
    except Exception as e:
        elapsed = round((time.time() - t0) * 1000)
        if st.sidebar:
            st.sidebar.error(
                f"{method} {path} failed ({elapsed}ms): {str(e)[:50]}")
        return {"ok": False, "error": str(e), "debug": {"url": url, "elapsed_ms": elapsed}}


def _get(path: str, **params) -> Dict[str, Any]:
    return _req_json("GET", path, params=params)


def _post(path: str, payload: Dict[str, Any], *, timeout: int = 30) -> Dict[str, Any]:
    return _req_json("POST", path, timeout=timeout, json=payload)


def _delete(path: str) -> Dict[str, Any]:
    return _req_json("DELETE", path)


# Simple connectivity check
with st.sidebar.expander("API Status", expanded=False):
    st.caption(f"Base: `{API}`")
    ping_result = _get("/")
    if ping_result.get("ok"):
        st.success("Connected ✅")
    else:
        st.error("Connection failed")
        st.json(ping_result)

# =========================
# Profile helpers
# =========================


def load_profile(uid: str) -> Dict[str, Any]:
    res = _get(f"/profile/{uid}")
    if isinstance(res, dict) and "profile" in res:
        return res["profile"]
    return {"user_id": uid, "username": st.session_state.username}


def save_profile(p: Dict[str, Any]) -> Dict[str, Any]:
    return _post(f"/profile/{p.get('user_id', 'demo-user')}", p)


def search_from_profile(p: Dict[str, Any], include_mock: bool) -> Dict[str, Any]:
    city = (p.get("city") or "").strip()
    country = (p.get("country") or "").strip().upper()

    if not city or len(country) != 2:
        return {
            "count": 0,
            "items": [],
            "debug": {"reason": "invalid_location", "city": city, "country": country},
        }

    params = {
        "city": city,
        "country": country,
        "days_ahead": int(p.get("days_ahead", 120)),
        "start_in_days": int(p.get("start_in_days", 0)),
        "include_mock": include_mock,
    }

    if p.get("keywords"):
        params["query"] = p["keywords"]

    result = _get("/events/search", **params)
    return result if isinstance(result, dict) else {"count": 0, "items": []}

# =========================
# UI components
# =========================


def event_card(e: Dict[str, Any], key: str, user_id: str):
    with st.container():
        title = e.get("title", "Untitled Event")
        st.markdown(f"### {title}")

        # Event details
        details = []
        if e.get("venue_name"):
            details.append(f"📍 {e['venue_name']}")
        if e.get("city") and e.get("country"):
            details.append(f"{e['city']}, {e['country']}")
        if e.get("start_time"):
            details.append(f"🕐 {e['start_time']}")
        if e.get("category"):
            details.append(f"🏷️ {e['category']}")

        if details:
            st.caption(" • ".join(details))

        # Description
        desc = e.get("description")
        if desc and desc != "Event" and len(desc) > 10:
            st.text(desc[:200] + "..." if len(desc) > 200 else desc)

        # Image
        if e.get("image_url"):
            try:
                st.image(e["image_url"], use_column_width=True)
            except Exception:
                pass

        # Action buttons
        col1, col2, col3 = st.columns([2, 1, 1])

        with col1:
            if e.get("url"):
                st.markdown(f"[🔗 View Details]({e['url']})")

        with col2:
            if st.button("💾 Save", key=f"save_{key}"):
                save_result = _post("/saved", {"user_id": user_id, "event": e})
                if save_result.get("ok"):
                    st.success("Saved!")
                else:
                    st.error("Save failed")

        with col3:
            price = e.get("min_price")
            if price is not None:
                currency = e.get("currency", "")
                st.write(f"💰 From {price} {currency}".strip())

        st.divider()


# =========================
# Main App
# =========================
tabs = st.tabs(["🏠 Discover", "💬 Chat", "⚙️ Settings"])

# ---------- SETTINGS TAB ----------
with tabs[2]:
    st.header("⚙️ Settings")
    st.caption("Configure your preferences for personalized recommendations.")

    # Load current profile
    profile = load_profile(st.session_state.user_id)

    # Settings form
    with st.form("settings_form"):
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Account")
            username = st.text_input(
                "Username",
                value=profile.get("username", st.session_state.username)
            )
            user_id = st.text_input(
                "User ID",
                value=profile.get("user_id", st.session_state.user_id)
            )

        with col2:
            st.subheader("Location")
            city = st.text_input(
                "Home City",
                value=profile.get("city", "Vilnius"),
                help="Your home city for event recommendations"
            )
            country = st.text_input(
                "Country Code",
                value=profile.get("country", "LT"),
                max_chars=2,
                help="ISO-2 country code (e.g., LT, US, GB)"
            ).upper()

        col3, col4 = st.columns(2)

        with col3:
            st.subheader("Search Preferences")
            days_ahead = st.slider(
                "Days ahead to search",
                min_value=7,
                max_value=365,
                value=int(profile.get("days_ahead", 120))
            )
            start_in_days = st.slider(
                "Start search in X days",
                min_value=0,
                max_value=30,
                value=int(profile.get("start_in_days", 0))
            )

        with col4:
            st.subheader("Interests")
            keywords = st.text_input(
                "Search Keywords",
                value=profile.get("keywords", ""),
                help="Comma-separated keywords (e.g., music, sports, theater)"
            )
            passions_text = st.text_area(
                "Interests/Passions",
                value=", ".join(profile.get("passions", [])),
                help="Your interests for better recommendations"
            )

        # Advanced options
        with st.expander("Advanced Options"):
            include_mock = st.checkbox(
                "Include mock data (for testing)",
                value=False
            )

        # Submit button
        if st.form_submit_button("💾 Save Settings", type="primary"):
            # Parse passions
            passions = [p.strip()
                        for p in passions_text.split(",") if p.strip()]

            # Build profile payload
            new_profile = {
                "user_id": user_id,
                "username": username,
                "city": city.strip(),
                "country": country.strip(),
                "days_ahead": days_ahead,
                "start_in_days": start_in_days,
                "keywords": keywords.strip() or None,
                "passions": passions,
            }

            # Save profile
            result = save_profile(new_profile)

            if result.get("ok"):
                st.success("✅ Settings saved successfully!")
                # Update session state
                st.session_state.user_id = user_id
                st.session_state.username = username
                st.rerun()
            else:
                st.error(
                    f"❌ Failed to save: {result.get('error', 'Unknown error')}")

# ---------- DISCOVER TAB ----------
with tabs[0]:
    st.header("🏠 Discover Events")

    # Load profile for search
    profile = load_profile(st.session_state.user_id)

    # Search controls
    col1, col2 = st.columns([1, 3])

    with col1:
        st.subheader("🎛️ Controls")
        st.caption("Based on your Settings")

        include_mock_feed = st.checkbox("Include test data", value=False)

        if st.button("🔄 Refresh Feed", type="primary"):
            st.rerun()

        # Show current search params
        with st.expander("Search Parameters"):
            st.json({
                "city": profile.get("city", "Not set"),
                "country": profile.get("country", "Not set"),
                "days_ahead": profile.get("days_ahead", 120),
                "keywords": profile.get("keywords", "None")
            })

    with col2:
        st.subheader("📅 Recommended Events")

        # Check if location is set
        if not (profile.get("city") and profile.get("country")):
            st.warning(
                "🏠 Please set your **Home City** and **Country** in Settings to see recommendations."
            )
        else:
            # Search for events
            with st.spinner("🔍 Finding events..."):
                search_result = search_from_profile(profile, include_mock_feed)

            # Display results
            items = search_result.get("items", [])

            if not items:
                st.info(
                    "🤷 No events found matching your criteria. Try adjusting your settings or expanding the date range.")

                # Show debug info
                debug = search_result.get("debug", {})
                if debug:
                    with st.expander("🔧 Debug Information"):
                        st.json(debug)
            else:
                st.success(f"✨ Found {len(items)} events for you!")

                # Sort by user preferences
                passions = {p.lower() for p in profile.get("passions", [])}

                def relevance_score(event):
                    score = 0
                    title = (event.get("title", "")).lower()
                    category = (event.get("category", "")).lower()

                    for passion in passions:
                        if passion in title:
                            score += 3
                        if passion in category:
                            score += 2

                    return score

                # Sort by relevance (highest first)
                items.sort(key=relevance_score, reverse=True)

                # Display events
                for idx, event in enumerate(items):
                    event_card(
                        event,
                        key=f"discover_{idx}_{event.get('title', '')[:20]}",
                        user_id=st.session_state.user_id
                    )

# ---------- CHAT TAB ----------
with tabs[1]:
    st.header("💬 Chat with Socialite")
    st.caption(
        "Ask me about events, get recommendations, or plan your activities!")

    # Chat interface
    profile = load_profile(st.session_state.user_id)

    message = st.text_input(
        "💭 What are you looking for?",
        placeholder="e.g., 'concerts this weekend in my city' or 'comedy shows next month'"
    )

    if st.button("📤 Send", type="primary") and message:
        # Prepare chat payload
        chat_payload = {
            "user_id": st.session_state.user_id,
            "username": st.session_state.username,
            "message": message,
            "city": profile.get("city"),
            "country": profile.get("country"),
        }

        # Send to agent
        with st.spinner("🤔 Thinking..."):
            response = _post("/agent/chat", chat_payload, timeout=60)

        # Display response
        if response.get("error"):
            st.error(f"❌ Chat failed: {response['error']}")
        else:
            # Show answer
            answer = response.get(
                "answer", "I'm not sure how to help with that.")
            st.markdown(f"🤖 **Socialite**: {answer}")

            # Show recommended events if any
            events = response.get("items", [])
            if events:
                st.markdown("### 🎯 Recommended Events")
                for idx, event in enumerate(events[:5]):  # Limit to 5 events
                    event_card(
                        event,
                        key=f"chat_{idx}_{event.get('title', '')[:20]}",
                        user_id=st.session_state.user_id
                    )

    # Subscription section
    st.divider()
    st.subheader("📬 Subscriptions")
    st.caption("Get personalized event digests delivered regularly.")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("📅 Subscribe Weekly"):
            sub_payload = {
                "user_id": st.session_state.user_id,
                "city": profile.get("city"),
                "country": profile.get("country"),
                "cadence": "WEEKLY",
                "keywords": profile.get("passions", []),
            }

            result = _post("/agent/subscribe", sub_payload)

            if result.get("ok"):
                st.success("✅ Subscribed to weekly digest!")
            else:
                hint = result.get("hint", "Subscription feature coming soon!")
                st.info(f"ℹ️ {hint}")

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
                st.info("📭 No digest available yet. Try subscribing first!")

# =========================
# Footer
# =========================
st.divider()
st.caption("🎟️ Socialite - Discover amazing events in your city!")
