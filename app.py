from __future__ import annotations

import hashlib
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st
from datetime import datetime

from social_agent_ai.services.storage import get_store


# ===============================
# Config & lightweight helpers
# ===============================

def _get_api_base() -> str:
    """Secrets -> ENV -> localhost fallback"""
    if hasattr(st, "secrets") and "API_BASE" in st.secrets:
        return str(st.secrets["API_BASE"]).rstrip("/")
    env_val = os.environ.get("API_BASE")
    if env_val:
        return env_val.rstrip("/")
    return "http://127.0.0.1:8000"


def _stable_id(rec: Dict[str, Any]) -> str:
    src = f"{rec.get('source','')}-{rec.get('external_id','')}-{rec.get('title','')}-{rec.get('start_time','')}"
    return hashlib.sha1(src.encode("utf-8")).hexdigest()


def _human_time(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y · %H:%M")
    except Exception:
        return iso


def _pretty_source(source: Optional[str]) -> str:
    if not source:
        return "unknown"
    # normalize simple web domains
    s = source.replace("https://", "").replace("http://", "").rstrip("/")
    if s.startswith("web:"):
        s = s.split(":", 1)[1]
    return s


# ===============================
# HTTP with retry/backoff
# ===============================

def _classify_error(e: Exception) -> Tuple[str, str]:
    """return (title, body) for UI"""
    if isinstance(e, requests.HTTPError):
        status = e.response.status_code if e.response is not None else "?"
        url = getattr(e.response, "url", "")
        if status == 404:
            return ("404 Not Found",
                    f"Endpoint not found at **{url}**. Check API base URL in **Settings**.")
        if status in (500, 502, 503, 504):
            return (f"{status} Server error",
                    "The API is temporarily unavailable. Try again in a moment.")
        return (f"HTTP {status}", f"{e}")
    if isinstance(e, requests.Timeout):
        return ("Timeout", "The request took too long. Try again or narrow your search.")
    if isinstance(e, requests.ConnectionError):
        return ("Connection error",
                "Could not reach the API. Is it running, and is your **API base** correct?")
    return ("Unexpected error", f"{e}")


def _api_get_retry(
    url: str,
    params: Dict[str, Any],
    *,
    attempts: int = 3,
    timeout: int = 20,
    backoff: float = 0.75,
) -> Dict[str, Any]:
    last: Optional[Exception] = None
    for i in range(1, attempts + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            if i >= attempts:
                break
            time.sleep(backoff * i)
    assert last is not None
    raise last


@st.cache_data(show_spinner=False, ttl=60)
def _api_get(api_base: str, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{api_base.rstrip('/')}/{path.lstrip('/')}"
    return _api_get_retry(url, params)


@st.cache_data(show_spinner=False, ttl=600)
def _get_providers(api_base: str) -> List[str]:
    """
    Ask the API for a list of web discovery domains / providers.
    Falls back to a small default list if endpoint is missing.
    """
    try:
        data = _api_get(api_base, "/events/providers", {})
        # Expect: {"web": ["bilietai.lt", ...], "apis": ["ticketmaster", ...]} OR simple list
        if isinstance(data, dict):
            # merge any lists we find
            doms: List[str] = []
            for v in data.values():
                if isinstance(v, list):
                    doms.extend([str(x) for x in v])
            return sorted(set(doms))
        if isinstance(data, list):
            return sorted({str(x) for x in data})
    except Exception:
        pass
    # Fallback defaults (safe to ignore if API doesn't support)
    return ["bilietai.lt", "piletilevi.ee", "bilesuserviss.lv", "tiketa.lt"]


# ===============================
# Streamlit state & chrome
# ===============================

st.set_page_config(page_title="Socialite", layout="wide")

if "prefs" not in st.session_state:
    st.session_state.prefs = {
        "api_base_override": None,
        "default_city": "Vilnius",
        "default_country": "LT",
        "include_mock": False,
        "days_ahead": 120,
        "start_in_days": 0,
    }

if "last_results" not in st.session_state:
    st.session_state.last_results = []

API_BASE = st.session_state.prefs["api_base_override"] or _get_api_base()
store = get_store()

tabs = st.tabs(["Discover", "Saved ⭐", "Settings"])

# ===============================
# Discover
# ===============================
with tabs[0]:
    st.write("Use the filters in the left sidebar, then click **Search**.")

    with st.sidebar:
        st.header("Search")
        city = st.text_input("City", st.session_state.prefs["default_city"])
        country = st.text_input("Country (ISO-2)", st.session_state.prefs["default_country"])
        start_in_days = st.number_input("Start in (days)", min_value=0,
                                        value=st.session_state.prefs["start_in_days"], step=1)
        days_ahead = st.number_input("Days ahead", min_value=1,
                                     value=st.session_state.prefs["days_ahead"], step=1)
        query = st.text_input("Keyword (optional)", value="")
        include_mock = st.checkbox("Include mock data", value=st.session_state.prefs["include_mock"])

        st.divider()
        st.subheader("Providers")
        with st.spinner("Loading providers…"):
            providers = _get_providers(API_BASE)
        if providers:
            sel = st.multiselect(
                "Limit to these sources (optional)",
                options=providers,
                default=providers,  # preselect all
            )
        else:
            sel = []
            st.caption("No provider list available from API; searching with API defaults.")

        do_search = st.button("🔎 Search", use_container_width=True)

    if do_search:
        params = {
            "city": city,
            "country": country,
            "start_in_days": int(start_in_days),
            "days_ahead": int(days_ahead),
            "query": query,
            "include_mock": str(include_mock).lower(),
        }
        # Send both names the backend *might* accept for compatibility
        if sel:
            params["domains"] = ",".join(sel)
            params["sources"] = ",".join(sel)

        try:
            with st.spinner("Finding events…"):
                data = _api_get(API_BASE, "/events/search", params)
                items: List[Dict[str, Any]] = data.get("items", [])
                st.session_state.last_results = items
                st.success(
                    f"Found {len(items)} event(s) for **{data.get('city', city)}**, "
                    f"**{data.get('country', country)}**"
                )
        except Exception as e:
            title, body = _classify_error(e)
            st.error(f"**{title}** — {body}")
            st.session_state.last_results = []

    items = st.session_state.last_results or []
    if not items:
        st.info("No events matched. Try broadening search or increasing the date range.")
    else:
        # toolbar
        left, right = st.columns([1, 1])
        with left:
            st.download_button(
                "Download CSV",
                data=pd.DataFrame(items).to_csv(index=False).encode("utf-8"),
                file_name="socialite_events.csv",
                mime="text/csv",
            )
        with right:
            st.caption("Click a card’s ⭐ to save it.")

        # cards
        for e in items:
            eid = e.get("external_id") or _stable_id(e)
            with st.container(border=True):
                top = st.columns([0.78, 0.22])
                with top[0]:
                    st.subheader(e.get("title") or "Untitled")
                    meta_line = []
                    meta_line.append(f"**When:** {_human_time(e.get('start_time'))}")
                    if e.get("venue_name"):
                        meta_line.append(f"**Where:** {e['venue_name']}")
                    st.write(" · ".join(meta_line))

                    line2 = []
                    if e.get("city") or e.get("country"):
                        line2.append(f"**Location:** {e.get('city','')} {e.get('country','')}".strip())
                    if e.get("category"):
                        line2.append(f"**Category:** {e['category']}")
                    st.write(" · ".join(line2))

                    # badges row
                    bcols = st.columns([0.2, 0.8])
                    with bcols[0]:
                        st.caption("Source")
                    with bcols[1]:
                        st.markdown(
                            f"<span style='padding:2px 6px;border:1px solid #555;border-radius:6px;'>"
                            f"{_pretty_source(e.get('source'))}"
                            f"</span>",
                            unsafe_allow_html=True,
                        )

                    if e.get("url"):
                        st.link_button("Open", e["url"])

                with top[1]:
                    label = "★ Save" if not store.is_saved(eid) else "★ Saved"
                    if st.button(label, key=f"save::{eid}"):
                        if store.is_saved(eid):
                            store.remove(eid)
                            st.toast("Removed from Saved", icon="⚠️")
                        else:
                            store.upsert(eid, e)
                            st.toast("Saved to favorites", icon="⭐")

# ===============================
# Saved
# ===============================
with tabs[1]:
    st.write("Your starred events are stored locally (`~/.socialite/saved.json`).")
    saved = store.list()
    if not saved:
        st.info("No saved items yet.")
    else:
        left, right = st.columns([1, 1])
        with left:
            st.download_button(
                "Export Saved (CSV)",
                data=pd.DataFrame([r["data"] for r in saved]).to_csv(index=False).encode("utf-8"),
                file_name="socialite_saved.csv",
                mime="text/csv",
            )
        with right:
            if st.button("Clear all ⭐", type="secondary"):
                for r in saved:
                    store.remove(r["id"])
                st.rerun()

        for row in saved:
            e = row["data"]
            eid = row["id"]
            with st.container(border=True):
                top = st.columns([0.8, 0.2])
                with top[0]:
                    st.subheader(e.get("title") or "Untitled")
                    st.write(f"**When:** {_human_time(e.get('start_time'))}")
                    st.caption(f"Source: {_pretty_source(e.get('source'))}")
                    if e.get("url"):
                        st.link_button("Open", e["url"])
                with top[1]:
                    if st.button("✖ Remove", key=f"remove::{eid}"):
                        store.remove(eid)
                        st.rerun()

# ===============================
# Settings
# ===============================
with tabs[2]:
    st.subheader("App preferences")
    st.caption("Stored in session while the app is running.")

    with st.form("prefs_form"):
        api_override = st.text_input(
            "API base override (optional)",
            value=st.session_state.prefs["api_base_override"] or "",
            help="e.g., https://socialite-api.onrender.com",
        )
        dc = st.text_input("Default city", st.session_state.prefs["default_city"])
        dco = st.text_input("Default country (ISO-2)", st.session_state.prefs["default_country"])
        sim = st.checkbox("Default: include mock data",
                          value=st.session_state.prefs["include_mock"])
        sday = st.number_input("Default: start in (days)", min_value=0,
                               value=st.session_state.prefs["start_in_days"], step=1)
        dahead = st.number_input("Default: days ahead", min_value=1,
                                 value=st.session_state.prefs["days_ahead"], step=1)
        submitted = st.form_submit_button("Save")

    if submitted:
        st.session_state.prefs.update(
            {
                "api_base_override": api_override.strip() or None,
                "default_city": dc.strip() or "Vilnius",
                "default_country": dco.strip() or "LT",
                "include_mock": bool(sim),
                "start_in_days": int(sday),
                "days_ahead": int(dahead),
            }
        )
        st.success("Preferences updated.")
        st.rerun()
