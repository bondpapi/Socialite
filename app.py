# social_agent_ai/ui/app.py
from __future__ import annotations

import os
import sys
from pathlib import Path

# --- Make imports robust no matter where this file is executed from ---
# Tries:
#   - installed package "social_agent_ai"
#   - repo layout when running "streamlit run social_agent_ai/ui/app.py"
#   - copied/flat layouts (e.g., Streamlit Cloud folder named "socialite/")
try:
    from social_agent_ai.services import storage  # type: ignore
except ModuleNotFoundError:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2],         # repo root: .../social_agent_ai/ui/app.py -> repo/
        here.parents[1],         # .../ui/
        Path.cwd(),              # current working directory
    ]
    for base in candidates:
        pkg_root = base / "social_agent_ai"
        if pkg_root.exists():
            sys.path.insert(0, str(base))
            break
    try:
        from social_agent_ai.services import storage  # type: ignore
    except ModuleNotFoundError:
        # final fallbacks for flat copies (services next to app.py)
        local_services = here.parent.parent / "services"
        if local_services.exists():
            sys.path.insert(0, str(local_services.parent))
        try:
            from services import storage  # type: ignore
        except Exception as e:
            raise

import streamlit as st
import pandas as pd
import requests
from typing import Any, Dict, List
from datetime import datetime, timedelta


def _get_api_base() -> str:
    # Prefer Streamlit secrets (Cloud), then ENV, then local default
    if hasattr(st, "secrets") and "API_BASE" in st.secrets:
        return st.secrets["API_BASE"].rstrip("/")
    return os.environ.get("API_BASE", "http://127.0.0.1:8000").rstrip("/")

API_BASE = _get_api_base()

st.set_page_config(page_title="Socialite", layout="wide")


# -------- helpers --------
def api_get(path: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    url = f"{API_BASE}{path}"
    r = requests.get(url, params=params or {}, timeout=20)
    r.raise_for_status()
    return r.json()


def api_search(
    city: str,
    country: str,
    days_ahead: int,
    start_in_days: int,
    include_mock: bool,
    query: str | None,
) -> Dict[str, Any]:
    params = {
        "city": city,
        "country": country,
        "days_ahead": days_ahead,
        "start_in_days": start_in_days,
        "include_mock": str(include_mock).lower(),
    }
    if query:
        params["query"] = query

    return api_get("/events/search", params=params)


def clean_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # ensure we always have consistent fields for display/export
    cleaned = []
    for e in items:
        cleaned.append(
            {
                "source": e.get("source"),
                "external_id": e.get("external_id"),
                "title": e.get("title") or "Untitled",
                "category": e.get("category"),
                "start_time": e.get("start_time"),
                "city": e.get("city"),
                "country": e.get("country"),
                "venue_name": e.get("venue_name"),
                "min_price": e.get("min_price"),
                "currency": e.get("currency"),
                "url": e.get("url"),
            }
        )
    return cleaned


def to_csv_bytes(items: List[Dict[str, Any]]) -> bytes:
    df = pd.DataFrame(items)
    return df.to_csv(index=False).encode("utf-8")


def event_subtitle(e: Dict[str, Any]) -> str:
    parts = []
    if e.get("venue_name"):
        parts.append(e["venue_name"])
    if e.get("city") or e.get("country"):
        parts.append(", ".join([p for p in [e.get("city"), e.get("country")] if p]))
    if e.get("start_time"):
        parts.append(e["start_time"])
    return " • ".join(parts)


def _event_key(e: Dict[str, Any]) -> str:
    ext = e.get("external_id") or ""
    title = e.get("title") or ""
    start = e.get("start_time") or ""
    venue = e.get("venue_name") or ""
    return f"{ext}|{title}|{start}|{venue}".strip()


# -------- sidebar controls --------
st.title("Socialite")

with st.sidebar:
    st.subheader("Search")
    col1, col2 = st.columns(2)
    with col1:
        city = st.text_input("City", value=st.session_state.get("city", "Vilnius"))
    with col2:
        country = st.text_input("Country (ISO-2)", value=st.session_state.get("country", "LT"))

    col3, col4 = st.columns(2)
    with col3:
        start_in_days = st.number_input("Start in (days)", min_value=0, max_value=365, value=0)
    with col4:
        days_ahead = st.number_input("Days ahead", min_value=1, max_value=365, value=90)

    query = st.text_input("Keyword (optional)", value="")
    include_mock = st.checkbox("Include mock data", value=False)

    run = st.button("🔎 Search", use_container_width=True)

tabs = st.tabs(["Discover", "Saved ⭐", "Settings"])


# -------- Discover --------
with tabs[0]:
    st.write("Use the filters in the sidebar, then click **Search**.")

    if run:
        st.session_state["city"] = city
        st.session_state["country"] = country

        with st.spinner("Finding events…"):
            try:
                data = api_search(
                    city=city,
                    country=country,
                    days_ahead=int(days_ahead),
                    start_in_days=int(start_in_days),
                    include_mock=bool(include_mock),
                    query=query or None,
                )
                items = clean_items(data.get("items", []))
                st.session_state.last_results = items
                count = data.get("count", len(items))
                st.success(f"Found {count} event(s) for **{data.get('city', city)}**, **{data.get('country', country)}**.")
            except requests.HTTPError as http_err:
                st.error(f"API error: {http_err}")
                items = []
            except Exception as err:
                st.error(f"Unexpected error: {err}")
                items = []

        if not items:
            st.info("No events matched. Try broadening search or increasing the date range.")
        else:
            # top controls: download CSV + small help
            left, right = st.columns([1, 1])
            with left:
                st.download_button(
                    "Download CSV",
                    data=to_csv_bytes(items),
                    file_name="socialite_events.csv",
                    mime="text/csv",
                )
            with right:
                st.caption("Click a card’s ⭐ to save it to your **Saved** tab.")

            # render cards in a responsive grid
            cols = st.columns(2)
            for idx, e in enumerate(items):
                c = cols[idx % 2]
                with c.container(border=True):
                    st.subheader(e["title"])
                    st.write(event_subtitle(e))
                    if e.get("url"):
                        st.link_button("Open", e["url"])
                    # actions
                    a1, a2, a3 = st.columns([1, 1, 1])
                    with a1:
                        if st.button("⭐ Save", key=f"save::{_event_key(e)}"):
                            storage.add_item(e)
                            st.toast("Saved!", icon="⭐")
                    with a2:
                        min_price = e.get("min_price")
                        currency = e.get("currency")
                        if min_price is not None and currency:
                            st.write(f"From {min_price} {currency}")
                        else:
                            st.write("Price: N/A")
                    with a3:
                        st.write(f"Source: {e.get('source') or 'web'}")


# -------- Saved --------
with tabs[1]:
    saved = storage.list_items()
    st.subheader(f"Saved events ({len(saved)})")

    if not saved:
        st.info("No saved events yet. Go to **Discover** and click ⭐.")
    else:
        top_l, top_r = st.columns([1, 1])
        with top_l:
            st.download_button(
                "Download Saved as CSV",
                data=to_csv_bytes(saved),
                file_name="socialite_saved.csv",
                mime="text/csv",
            )
        with top_r:
            if st.button("🗑️ Clear All", type="primary"):
                storage.clear_all()
                st.rerun()

        cols = st.columns(2)
        for idx, e in enumerate(saved):
            c = cols[idx % 2]
            with c.container(border=True):
                st.subheader(e.get("title") or "Untitled")
                st.write(event_subtitle(e))
                if e.get("url"):
                    st.link_button("Open", e["url"])
                # actions
                a1, a2 = st.columns([1, 1])
                with a1:
                    if st.button("Remove", key=f"remove::{_event_key(e)}"):
                        storage.remove_item(e)
                        st.rerun()
                with a2:
                    st.write(f"Source: {e.get('source') or 'web'}")


# -------- Settings --------
with tabs[2]:
    st.subheader("Providers")
    try:
        providers = api_get("/events/providers").get("providers", [])
        if providers:
            st.write(", ".join(providers))
        else:
            st.write("No providers reported.")
    except Exception as e:
        st.error(f"Could not fetch providers: {e}")

    st.divider()
    st.caption(
        "Saved items are stored at "
        f"`{storage.SAVED_PATH}` – handy if you want to back them up or inspect them."
    )
