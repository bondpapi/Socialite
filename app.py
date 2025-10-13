# ui/app.py
import os
import json
from typing import Optional

import pandas as pd
import requests
import streamlit as st

# ----------------------------
# Basic page setup
# ----------------------------
st.set_page_config(page_title="Socialite", layout="wide")
st.title("Socialite")

API_BASE = os.getenv("SOCIALITE_API_BASE", "http://127.0.0.1:8000")


# ----------------------------
# Small client helper
# ----------------------------
def api_get(path: str, params: dict) -> dict:
    url = f"{API_BASE.rstrip('/')}/{path.lstrip('/')}"
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def search_events(
    *,
    city: str,
    country: str,
    days_ahead: int,
    start_in_days: int,
    include_mock: bool,
    query: Optional[str],
    debug: bool = False,
) -> dict:
    params = dict(
        city=city,
        country=country,
        days_ahead=days_ahead,
        start_in_days=start_in_days,
        include_mock=str(include_mock).lower(),
        debug=str(bool(debug)).lower(),
    )
    if query:
        params["query"] = query
    return api_get("/events/search", params)


# ----------------------------
# Sidebar controls
# ----------------------------
st.sidebar.header("Search filters")

city = st.sidebar.text_input("City", value=os.getenv("DEFAULT_CITY", "Vilnius"))
country = st.sidebar.text_input("Country (ISO-2)", value=os.getenv("DEFAULT_COUNTRY", "LT"))
days_ahead = st.sidebar.slider("Days ahead", min_value=1, max_value=180, value=90, step=1)
start_in_days = st.sidebar.slider("Start in days", min_value=0, max_value=60, value=0, step=1)
query = st.sidebar.text_input("Query (optional)", value="")
include_mock = st.sidebar.toggle("Include mock provider", value=False)
show_debug = st.sidebar.toggle("Show provider debug", value=False)

run = st.sidebar.button("Search", type="primary")

# Keep last results across reruns
if "last_results" not in st.session_state:
    st.session_state.last_results = None

# ----------------------------
# Main area
# ----------------------------
tab1, tab2 = st.tabs(["Discover", "Providers"])

with tab1:
    st.write("Use the filters in the left sidebar, then click **Search**.")

    if run:
        with st.spinner("Finding events..."):
            try:
                data = search_events(
                    city=city,
                    country=country,
                    days_ahead=days_ahead,
                    start_in_days=start_in_days,
                    include_mock=include_mock,
                    query=query or None,
                    debug=show_debug,
                )
                st.session_state.last_results = data
            except Exception as e:
                st.error(f"Search failed: {e}")
                st.stop()

    data = st.session_state.last_results
    if not data:
        st.info("No search yet. Pick filters and press **Search**.")
    else:
        count = data.get("count", 0)
        st.success(
            f"Found **{count}** event(s) for **{data.get('city', city)}**, {data.get('country', country)}."
        )

        # Debug diagnostics (if requested)
        if show_debug and "debug" in data and data["debug"]:
            with st.expander("Provider diagnostics", expanded=False):
                df = pd.DataFrame(data["debug"])
                cols = [c for c in ["provider", "ok", "count", "ms", "error"] if c in df.columns]
                st.dataframe(df[cols] if cols else df, use_container_width=True)

        items = data.get("items", [])
        if not items:
            st.info("No events matched. Try broadening your search.")
        else:
            # Download CSV
            left, right = st.columns([1, 1])
            with left:
                st.download_button(
                    "Download CSV",
                    data=pd.DataFrame(items).to_csv(index=False).encode("utf-8"),
                    file_name="socialite_events.csv",
                    mime="text/csv",
                )
            with right:
                st.caption("Click a card’s ⭐ to save it. (UI stub)")

            # Render simple cards
            for e in items:
                with st.container(border=True):
                    top = st.columns([0.85, 0.15])
                    with top[0]:
                        st.subheader(e.get("title", "Untitled"))
                        meta = []
                        if e.get("start_time"):
                            meta.append(f"🗓 {e['start_time']}")
                        if e.get("venue_name"):
                            meta.append(f"📍 {e['venue_name']}")
                        st.write(" • ".join(meta))
                        if e.get("url"):
                            st.link_button("Open", e["url"])
                    with top[1]:
                        st.button("⭐ Save", key=f"save::{e.get('external_id', id(e))}")

with tab2:
    try:
        providers = api_get("/events/providers", params={})
        df = pd.DataFrame({"providers": providers.get("providers", [])})
        st.dataframe(df, use_container_width=True, height=250)
    except Exception as e:
        st.error(f"Failed to load providers: {e}")
