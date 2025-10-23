import os
from datetime import datetime, timedelta
from typing import Dict, Any, List
import pandas as pd
import requests
import streamlit as st

# ------------------ Config / API base ------------------
def _get_api_base() -> str:
    try:
        if getattr(st, "secrets", None) and "API_BASE" in st.secrets:
            return str(st.secrets["API_BASE"]).rstrip("/")
    except Exception:
        pass
    val = os.environ.get("API_BASE")
    if val:
        return val.rstrip("/")
    return "http://127.0.0.1:8000"


API_BASE = _get_api_base()
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Kaunas")
DEFAULT_COUNTRY = os.getenv("DEFAULT_COUNTRY", "LT")

st.set_page_config(page_title="Socialite", layout="wide")

# ------------------ Session state ------------------
if "user" not in st.session_state:
    st.session_state.user = {"user_id": "demo-user", "username": "demo"}
if "last_results" not in st.session_state:
    st.session_state.last_results = []
if "saved" not in st.session_state:
    st.session_state.saved = []
if "chatlog" not in st.session_state:
    st.session_state.chatlog = []

# ------------------ Helpers ------------------
def _api_get(path: str, params=None):
    r = requests.get(f"{API_BASE}{path}", params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def _api_post(path: str, json_body=None):
    r = requests.post(f"{API_BASE}{path}", json=json_body, timeout=60)
    r.raise_for_status()
    return r.json()


def _fetch_profile(user_id: str):
    try:
        return _api_get(f"/profile/{user_id}")
    except Exception:
        return {}


def _save_profile(user_id: str, home_city: str, home_country: str, passions: List[str]):
    payload = {
        "home_city": home_city or None,
        "home_country": home_country or None,
        "passions": passions or [],
    }
    return _api_post(f"/profile/{user_id}", payload)


def _search_events(city, country, days_ahead, start_in_days, include_mock, query):
    params = {
        "city": city,
        "country": country,
        "days_ahead": int(days_ahead),
        "start_in_days": int(start_in_days),
        "include_mock": bool(include_mock),
    }
    if query:
        params["query"] = query
    return _api_get("/events/search", params)


def _agent_chat(user_id: str, message: str):
    payload = {"user_id": user_id, "message": message}
    return _api_post("/agent/chat", payload)


def _read_digest(user_id: str):
    return _api_get(f"/agent/digest/{user_id}")


# ------------------ Sidebar (search form) ------------------
with st.sidebar:
    st.header("Search")
    city = st.text_input("City", value=DEFAULT_CITY)
    country = st.text_input("Country (ISO-2)", value=DEFAULT_COUNTRY)
    start_in_days = st.number_input(
        "Start in (days)", min_value=0, value=0, step=1)
    days_ahead = st.number_input("Days ahead", min_value=1, value=120, step=1)
    query = st.text_input("Keyword (optional)", value="sports")
    include_mock = st.checkbox("Include mock data", value=False)
    run_search = st.button("🔎 Search")

st.title("Socialite")

tabs = st.tabs(["Discover", "Chat 🤖", "Settings"])

# ------------------ Discover Tab ------------------
with tabs[0]:
    st.write("Use the filters in the left sidebar, then click **Search**.")
    items: List[Dict[str, Any]] = []
    if run_search:
        with st.spinner("Finding events..."):
            try:
                data = _search_events(
                    city, country, days_ahead, start_in_days, include_mock, query)
                items = data.get("items", [])
                st.session_state.last_results = items
                count = data.get("count", len(items))
                st.success(
                    f"Found {count} event(s) for **{data.get('city', city)}**, **{data.get('country', country)}**"
                )
            except requests.HTTPError as e:
                st.error(f"API error: {e}")
                items = []
            except Exception as e:
                st.error(f"Unexpected error: {e}")
                items = []

    # show last results if no fresh search
    if (not run_search) and st.session_state.last_results and not items:
        items = st.session_state.last_results
        st.caption("Showing last results (cached). Click **Search** to refresh.")

    if not items:
        st.info(
            "No events matched. Try broadening search or increasing the date range.")
    else:
        # Top controls
        left, right = st.columns([1, 1])
        with left:
            df = pd.DataFrame(items)
            st.download_button(
                "Download CSV",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name="socialite_events.csv",
                mime="text/csv",
            )
        with right:
            st.caption("Click a card’s ⭐ to save it.")

        # Cards
        for e in items:
            with st.container():
                top = st.columns([0.85, 0.15])
                with top[0]:
                    st.subheader(e.get("title") or "Untitled")
                    sub = []
                    if e.get("venue_name"):
                        sub.append(e["venue_name"])
                    if e.get("city"):
                        sub.append(e["city"])
                    if e.get("country"):
                        sub.append(e["country"])
                    st.write(", ".join([s for s in sub if s]))
                with top[1]:
                    key = f"save::{e.get('external_id') or e.get('title')}"
                    if st.button("⭐ Save", key=key):
                        st.session_state.saved.append(e)
                        st.success("Saved!")

                meta = []
                if e.get("category"):
                    meta.append(f"**Category:** {e['category']}")
                if e.get("start_time"):
                    meta.append(f"**Start:** {e['start_time']}")
                if e.get("min_price") is not None:
                    meta.append(
                        f"**From:** {e['min_price']} {e.get('currency', '')}".strip())
                if meta:
                    st.write(" • ".join(meta))
                if e.get("url"):
                    st.write(f"[Open event]({e['url']})")

    # Saved items (in this session)
    if st.session_state.saved:
        st.markdown("### ⭐ Saved (this session)")
        for e in st.session_state.saved:
            with st.expander(e.get("title") or "Saved event"):
                st.json(e, expanded=False)

# ------------------ Chat Tab ------------------
with tabs[1]:
    st.header("Chat with Socialite 🤖")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        username = st.text_input(
            "Username", value=st.session_state.user["username"])
    with col2:
        user_id = st.text_input(
            "User ID", value=st.session_state.user["user_id"])
    with col3:
        if st.button("Login (mock)"):
            try:
                out = _api_post("/auth/mock-login", {"username": username})
                st.session_state.user = {
                    "user_id": out["user_id"], "username": username}
                st.success(f"Signed in as {username} ({out['user_id']})")
            except Exception as e:
                st.error(f"Login failed: {e}")

    # show chat history
    for entry in st.session_state.chatlog:
        # each entry expected to be a (role, text) tuple/list
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            role, text = entry
        else:
            role, text = "user", str(entry)
        with st.chat_message(role):
            st.write(text)

    prompt = st.chat_input(
        "Ask me for plans, search something, or 'subscribe me weekly' …")
    if prompt:
        st.session_state.chatlog.append(("user", prompt))
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                try:
                    res = _agent_chat(st.session_state.user["user_id"], prompt)
                    reply = res.get("reply", "")
                    st.session_state.chatlog.append(("assistant", reply))
                    st.write(reply)
                except Exception as e:
                    st.error(f"Agent error: {e}")

    st.divider()
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("🔔 Fetch digest now"):
            try:
                d = _read_digest(st.session_state.user["user_id"])
                items = d.get("items", [])
                if not items:
                    st.info("No pending digests.")
                else:
                    st.success(f"Got {len(items)} new picks for you:")
                    for e in items:
                        st.markdown(
                            f"- **{e.get('title', '(untitled)')}** — {e.get('city', '')} {e.get('country', '')}")
            except Exception as e:
                st.error(f"Digest error: {e}")
    with c2:
        st.caption(
            "Digest is produced by the server scheduler. Use Settings to set your city & passions.")

# ------------------ Settings Tab ------------------
with tabs[2]:
    st.header("Settings")
    st.caption("Preferences are used by the agent & digest.")

    # load profile
    prof = _fetch_profile(st.session_state.user["user_id"]) or {}
    ph_city = prof.get("home_city") or ""
    ph_country = prof.get("home_country") or ""
    ph_passions = ", ".join(prof.get("passions") or [])

    s1, s2 = st.columns([1, 1])
    with s1:
        home_city = st.text_input("Home city", value=ph_city)
        home_country = st.text_input("Home country (ISO-2)", value=ph_country)
    with s2:
        passions_raw = st.text_input(
            "Passions (comma-separated)", value=ph_passions)

    if st.button("💾 Save preferences"):
        passions = [p.strip() for p in passions_raw.split(",") if p.strip()]
        try:
            _save_profile(
                st.session_state.user["user_id"], home_city, home_country, passions)
            st.success("Preferences saved.")
        except Exception as e:
            st.error(f"Save failed: {e}")

    st.divider()
    st.subheader("Subscriptions")
    st.caption("Ask the chat: 'subscribe me weekly' or 'subscribe me daily'.")
