from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import streamlit as st


def _get_api_base() -> str:
    if hasattr(st, "secrets") and "API_BASE" in st.secrets:
        return st.secrets["API_BASE"].rstrip("/")
    return os.environ.get("API_BASE", "http://127.0.0.1:8000").rstrip("/")


API_BASE = _get_api_base()

st.set_page_config(page_title="Socialite", layout="wide")
st.title("Socialite")

# ---------- Identity ----------
def ensure_user() -> str:
    if "user_id" not in st.session_state:
        st.session_state.user_id = str(uuid.uuid4())
        st.session_state.display_name = None
    return st.session_state.user_id


def api_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{API_BASE}{path}"
    r = requests.get(url, params=params or {}, timeout=20)
    r.raise_for_status()
    return r.json()


def api_post(path: str, json_obj: Any) -> Dict[str, Any]:
    url = f"{API_BASE}{path}"
    r = requests.post(url, json=json_obj, timeout=20)
    r.raise_for_status()
    return r.json()


def api_delete(path: str) -> Dict[str, Any]:
    url = f"{API_BASE}{path}"
    r = requests.delete(url, timeout=20)
    r.raise_for_status()
    return r.json()


# ---------- Sidebar ----------
with st.sidebar:
    st.header("Search")
    city = st.text_input("City", "Kaunas")
    country = st.text_input("Country (ISO-2)", "LT")
    start_in_days = st.number_input("Start in (days)", min_value=0, max_value=365, value=0, step=1)
    days_ahead = st.number_input("Days ahead", min_value=1, max_value=365, value=120, step=1)
    keyword = st.text_input("Keyword (optional)", "")
    include_mock = st.checkbox("Include mock data", value=False)
    run = st.button("🔎 Search")

tabs = st.tabs(["Discover", "Saved ⭐", "Settings"])

# ---------- Discover ----------
with tabs[0]:
    st.write("Use the filters in the left sidebar, then click **Search**.")
    if run:
        user_id = ensure_user()
        params = dict(
            city=city,
            country=country,
            start_in_days=int(start_in_days),
            days_ahead=int(days_ahead),
            include_mock=bool(include_mock),
            query=keyword or None,
        )
        with st.spinner("Finding events..."):
            try:
                data = api_get("/events/search", params=params)
                items = data.get("items", [])
                st.success(f"Found **{len(items)}** event(s) for **{data.get('city', city)}**, {data.get('country', country)}")

                if not items:
                    st.info("No events matched. Try broadening your search or increasing the date range.")
                else:
                    left, right = st.columns((1, 1))
                    with left:
                        st.download_button(
                            "Download CSV",
                            data=pd.DataFrame(items).to_csv(index=False).encode("utf-8"),
                            file_name="socialite_events.csv",
                            mime="text/csv",
                        )
                    with right:
                        st.caption("Click a card’s ⭐ to save it.")

                    for e in items:
                        ek = e.get("_event_key") or f"{e.get('source')}::{e.get('external_id') or e.get('url') or ''}"
                        with st.container(border=True):
                            c1, c2 = st.columns((0.85, 0.15))
                            with c1:
                                st.subheader(e.get("title") or "Untitled")
                                meta = []
                                if e.get("venue_name"):
                                    meta.append(e["venue_name"])
                                if e.get("start_time"):
                                    meta.append(str(e["start_time"]))
                                st.write(" • ".join(meta))
                                if e.get("url"):
                                    st.markdown(f"[Open link]({e['url']})")
                            with c2:
                                if st.button("⭐ Save", key=f"save::{ek}"):
                                    try:
                                        api_post(f"/users/{user_id}/saved", e)
                                        st.toast("Saved!", icon="✅")
                                    except Exception as ex:
                                        st.error(f"Failed to save: {ex}")
            except requests.HTTPError as ex:
                st.error(f"API error: {ex}")
            except Exception as ex:
                st.error(f"Unexpected error: {ex}")

# ---------- Saved ----------
with tabs[1]:
    user_id = ensure_user()
    try:
        data = api_get(f"/users/{user_id}/saved")
        items = data.get("items", [])
        st.subheader(f"Saved items ({len(items)})")
        if not items:
            st.info("You haven’t saved anything yet.")
        else:
            for e in items:
                ek = e.get("_event_key")
                with st.container(border=True):
                    c1, c2 = st.columns((0.85, 0.15))
                    with c1:
                        st.write(f"**{e.get('title') or 'Untitled'}**")
                        meta = []
                        if e.get('venue_name'):
                            meta.append(e['venue_name'])
                        if e.get('start_time'):
                            meta.append(str(e['start_time']))
                        st.caption(" • ".join(meta))
                        if e.get("url"):
                            st.markdown(f"[Open link]({e['url']})")
                    with c2:
                        if st.button("🗑️ Unsave", key=f"unsave::{ek}"):
                            try:
                                api_delete(f"/users/{user_id}/saved/{ek}")
                                st.experimental_rerun()
                            except Exception as ex:
                                st.error(f"Failed to unsave: {ex}")
    except Exception as ex:
        st.error(f"Could not load saved items: {ex}")

# ---------- Settings ----------
with tabs[2]:
    user_id = ensure_user()
    st.caption(f"Your user ID (local session): `{user_id}`")
    display_name = st.text_input("Display name (optional)", value=st.session_state.get("display_name") or "")
    if st.button("Save profile"):
        try:
            resp = api_post(f"/users/{user_id}/profile", {"display_name": display_name or None})
            st.session_state.display_name = (resp.get("profile") or {}).get("display_name")
            st.success("Profile saved")
        except Exception as ex:
            st.error(f"Failed to save profile: {ex}")

    st.divider()
    with st.expander("📊 Usage & Costs", expanded=False):
        cols = st.columns(2)
        with cols[0]:
            if st.button("Refresh usage"):
                st.session_state._usage_nonce = (st.session_state.get("_usage_nonce", 0) + 1)

        # HTTP summary
        try:
            http_sum = api_get("/metrics/http/summary")
            st.subheader("HTTP Summary")
            st.write(http_sum.get("totals", {}))
            df_routes = pd.DataFrame(http_sum.get("routes", []))
            if not df_routes.empty:
                st.dataframe(df_routes, use_container_width=True)
        except Exception as ex:
            st.warning(f"Could not load HTTP summary: {ex}")

        # Timeline chart
        try:
            tl = api_get("/metrics/http/timeline", params={"last_n": 200}).get("items", [])
            df_tl = pd.DataFrame(tl)
            if not df_tl.empty:
                st.subheader("Recent durations (ms)")
                st.line_chart(df_tl[["duration_ms"]])
        except Exception as ex:
            st.warning(f"Could not load timeline: {ex}")

        # LLM summary (if you log it)
        try:
            llm_sum = api_get("/metrics/llm/summary")
            st.subheader("LLM Usage (optional)")
            st.write(llm_sum.get("totals", {}))
            df_models = pd.DataFrame(llm_sum.get("models", []))
            if not df_models.empty:
                st.dataframe(df_models, use_container_width=True)
        except Exception as ex:
            st.info("No LLM usage yet (or endpoint not available).")
