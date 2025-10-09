import streamlit as st
import requests
from datetime import date, timedelta

# ui/app.py
import streamlit as st

st.set_page_config(page_title="Socialite", page_icon="🎟️", layout="wide")
st.title("Socialite")
st.caption("Your Events Concierge")  # optional tagline

# Optional: brand the sidebar
st.sidebar.title("Socialite")
# st.sidebar.image("assets/logo.png", use_column_width=True)  # if you add a logo

col1, col2, col3, col4 = st.columns(4)
with col1:
    city = st.text_input("City", value="Vilnius")
with col2:
    country = st.text_input("Country (ISO2)", value="LT")
with col3:
    days_ahead = st.slider("Days ahead", 7, 180, 60)
with col4:
    start_in_days = st.slider("Start in (days)", 0, 60, 0)

query = st.text_input("Query (optional)", value="concert")
include_mock = st.checkbox("Include mock data", value=False)

if st.button("Search"):
    with st.spinner("Searching…"):
        url = "http://127.0.0.1:8000/events/search"
        params = dict(
            city=city, country=country, days_ahead=days_ahead,
            start_in_days=start_in_days, include_mock=str(include_mock).lower(),
            query=query
        )
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])

        st.subheader(f"Results — {len(items)} found")
        for e in items:
            with st.container(border=True):
                st.markdown(f"**{e.get('title','(no title)')}**")
                left, right = st.columns([3,2])
                with left:
                    st.write(f"🕒 {e.get('start_time','?')}")
                    st.write(f"📍 {e.get('venue_name','?')}, {e.get('city','?')}")
                    st.write(f"🏷️ {e.get('category','?')} • {e.get('source','?')}")
                    min_price = e.get('min_price')
                    if min_price is not None:
                        st.write(f"💶 from {min_price} {e.get('currency','')}".strip())
                with right:
                    if e.get("url"):
                        st.link_button("Open tickets/site", e["url"])
