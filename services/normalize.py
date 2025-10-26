import re, hashlib

def normalize_text(s: str | None) -> str | None:
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    return s

def normalize_event(e: dict) -> dict:
    e = dict(e)
    e["title"]      = normalize_text(e.get("title"))
    e["venue_name"] = normalize_text(e.get("venue_name"))
    e["city"]       = normalize_text(e.get("city"))

    # stable id
    key = f'{e.get("title")}|{e.get("start_time")}|{e.get("venue_name")}|{e.get("city")}'
    e["id"] = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return e
