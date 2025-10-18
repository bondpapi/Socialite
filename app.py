# ui/app.py
from __future__ import annotations
import json
import os
from typing import Any, Dict, List, Optional

import streamlit as st
import requests_cache

from social_agent_ai.services.http import get as http_get
from social_agent_ai.services import ratings as rt


# ---------- config ----------
def _api_base() -> str:
    # Prefer Streamlit secrets (Cloud), then ENV, then local default
    if hasattr(st, "secrets") and "API_BASE" in st.secrets:
        return st.secrets["API_BASE"].rstrip("/")
    return os.getenv("API_BASE", "http://127.0.0.1:8000").rstrip("/")


API_BASE = _api_base()

# Transparent HTTP cache for ALL requests (including backend API)
requests_cache.install_cache("socialite_cache", backend="sqlite", expire_after=3600)

# DB init for ratings/saved
rt.init()

st.set_page_config(page_title="Socialite", layout="wide")

# ---------- helpers ----------
def _user_id() -> str:
    # Simple anonymous user id (extend later with auth)
    return "anon"


def _event_key(e: Dict[str, Any]) -> str:
    return f"{e.get('source')}::{e.get('external_id')}"


def _search_api(city: str, country: str, days_ahead: int, start_in_days: int, include_mock: bool, query: Optional[str]) -> Dict[str, Any]:
    params = {
        "city": city,
        "country": country,
        "days_ahead": days_ahead,
        "start_in_days": start_in_days,
        "include_mock": str(include_mock).lower(),
    }
    if query:
        params["query"] = query
    url = f"{API_BASE}/events/search"
    r = http_get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def _render_event_card(e: Dict[str, Any]):
    ek = _event_key(e)
    with st.container(border=True):
        left, right = st.columns([0.8, 0.2])
        with left:
            st.subheader(e.get("title") or "Untitled")
            meta = []
            if e.get("venue_name"): meta.append(e["venue_name"])
            if e.get("city"): meta.append(e["city"])
            if e.get("country"): meta.append(e["country"])
            if meta:
                st.caption(" • ".join(meta))
            st.write(f"[Open link]({e.get('url')})" if e.get("url") else "—")
        with right:
            # Save / Rating controls
            if st.button("⭐ Save", key=f"save_{ek}"):
                rt.save_item(_user_id(), e.get("external_id") or ek, json.dumps(e, ensure_ascii=False))
                st.toast("Saved")

            current = rt.get_rating(_user_id(), e.get("external_id") or ek) or 3
            rating = st.slider("Rate", 1, 5, value=int(current), key=f"rate_{ek}")
            if st.button("Save rating", key=f"rate_btn_{ek}"):
                rt.save_rating(_user_id(), e.get("external_id") or ek, int(rating))
                st.toast("Thanks for your feedback!")


# ---------- UI ----------
tabs = st.tabs(["Discover", "Saved ⭐", "Settings"])

with tabs[0]:
    with st.sidebar:
        st.header("Search")
        city = st.text_input("City", value="Kaunas")
        country = st.text_input("Country (ISO-2)", value="LT")
        start_in_days = st.number_input("Start in (days)", min_value=0, max_value=365, value=0, step=1)
        days_ahead = st.number_input("Days ahead", min_value=1, max_value=365, value=120, step=1)
        query = st.text_input("Keyword (optional)", value="")
        include_mock = st.checkbox("Include mock data", value=False)
        run = st.button("🔎 Search")

    st.title("Socialite")
    st.caption("Use the filters in the sidebar, then click **Search**.")

    if run:
        with st.spinner("Finding events..."):
            try:
                data = _search_api(
                    city=city,
                    country=country,
                    days_ahead=int(days_ahead),
                    start_in_days=int(start_in_days),
                    include_mock=bool(include_mock),
                    query=query or None,
                )
                items: List[Dict[str, Any]] = data.get("items", [])
                count = data.get("count", len(items))
                st.success(f"Found {count} event(s) for **{data.get('city', city)}**, **{data.get('country', country)}**")

                if not items:
                    st.info("No events matched. Try broadening your search or increasing the date range.")
                else:
                    # Controls row
                    c_left, c_right = st.columns([1, 1])
                    with c_left:
                        df = [{"title": e.get("title"), "when": e.get("start_time"), "city": e.get("city"), "url": e.get("url")} for e in items]
                        st.download_button(
                            "Download CSV",
                            data=_to_csv(df),
                            file_name="socialite_events.csv",
                            mime="text/csv",
                        )
                    with c_right:
                        st.caption("Click a card’s ⭐ to save it.")

                    # Cards
                    for e in items:
                        _render_event_card(e)

            except Exception as ex:
                st.error(f"API error: {ex}")

def _to_csv(rows: List[Dict[str, Any]]) -> bytes:
    if not rows:
        return b"title,when,city,url\n"
    # Manual tiny CSV to avoid extra dependency
    cols = ["title", "when", "city", "url"]
    out = [",".join(cols)]
    for r in rows:
        out.append(",".join((str(r.get(c, "") or "").replace(",", "，") for c in cols)))
    return ("\n".join(out) + "\n").encode("utf-8")

with tabs[1]:
    st.header("Saved ⭐")
    saved = list(rt.get_saved_items(_user_id()))
    if not saved:
        st.info("No saved items yet. Use ⭐ on event cards to save them.")
    else:
        for external_id, payload in saved:
            try:
                e = json.loads(payload)
            except Exception:
                e = {"title": "(Invalid payload)", "external_id": external_id}
            _render_event_card(e)
            if st.button("Remove", key=f"rm_{external_id}"):
                rt.delete_saved(_user_id(), external_id)
                st.experimental_rerun()

with tabs[2]:
    st.header("Settings")
    st.caption(f"API base: `{API_BASE}`")
    col1, col2 = st.columns([1,1])
    with col1:
        if st.button("Clear HTTP cache"):
            requests_cache.clear()
            st.success("Cache cleared.")
    with col2:
        st.caption("More settings coming soon.")
