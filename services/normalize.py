# social_agent_ai/services/normalize.py
import re, hashlib
from datetime import datetime

def normalize_text(s: str | None) -> str | None:
    if not s: return None
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def normalize_event(e: dict) -> dict:
    e = dict(e)
    e["title"]      = normalize_text(e.get("title"))
    e["venue_name"] = normalize_text(e.get("venue_name"))
    e["city"]       = normalize_text(e.get("city"))
    # ensure ISO8601 (if your WebDiscovery already emits ISO, this is a no-op)
    dt = e.get("start_time")
    if isinstance(dt, str):
        # keep as-is if already ISO; else you can try dateparser if you add it
        pass
    # stable id
    key = f'{e.get("title")}|{e.get("start_time")}|{e.get("venue_name")}|{e.get("city")}'
    e["id"] = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return e
