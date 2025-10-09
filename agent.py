# agent/agent.py
import os, requests
from datetime import datetime
from typing import Optional

# ---- Replace with your chosen LLM SDK ----
from openai import OpenAI
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

SYSTEM = """You recommend live events and social gatherings. Convert user asks into {city, country, query, start_in_days, days_ahead}.
Prefer Baltic cities (LT, LV, EE) unless user says otherwise. Be concise. If nothing is found, suggest nearby cities.
"""

def search_backend(city:str, country:str, query:Optional[str], start_in_days:int, days_ahead:int):
    url = "http://127.0.0.1:8000/events/search"
    params = dict(city=city, country=country, query=query or "",
                  start_in_days=start_in_days, days_ahead=days_ahead, include_mock="false")
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json().get("items", [])

def agent_reply(user_text: str) -> str:
    # 1) get params
    tool_schema = {
      "name":"to_params",
      "description":"Turn request into search parameters",
      "parameters":{
        "type":"object",
        "properties":{
          "city":{"type":"string"},
          "country":{"type":"string","description":"ISO2, e.g. LT, LV, EE"},
          "query":{"type":"string"},
          "start_in_days":{"type":"integer","minimum":0,"default":0},
          "days_ahead":{"type":"integer","minimum":1,"default":60}
        },
        "required":["city","country"]
      }
    }

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        tools=[{"type":"function","function":tool_schema}],
        messages=[
          {"role":"system", "content": SYSTEM},
          {"role":"user", "content": user_text}
        ]
    )

    call = (resp.choices[0].message.tool_calls or [None])[0]
    if not call:
        # fallback guess
        params = dict(city="Vilnius", country="LT", query=user_text, start_in_days=0, days_ahead=60)
    else:
        params = call.function.arguments  # dict per your SDK

    items = search_backend(**params)
    if not items:
        return f"No matches in {params['city']}, {params['country']} for “{params.get('query','')}”. Try a nearby city or broaden the dates?"

    # shortlist top 5
    items = items[:5]
    lines = [f"Top picks for {params['city']} ({params['country']}):"]
    for e in items:
        when = e.get("start_time","?")
        title = e.get("title","?")
        venue = e.get("venue_name","?")
        url   = e.get("url","")
        price = f" from {e['min_price']} {e.get('currency','')}" if e.get("min_price") else ""
        lines.append(f"- {when} • {title} @ {venue}{price}  {url}")
    return "\n".join(lines)

if __name__ == "__main__":
    print(agent_reply("Find rock concerts in Vilnius this month under 50 EUR"))
