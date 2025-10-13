# social_agent_ai/services/storage.py
from __future__ import annotations
from pathlib import Path
import json
from typing import Any, Dict, List

APP_DIR = Path.home() / ".socialite"
APP_DIR.mkdir(parents=True, exist_ok=True)
SAVED_PATH = APP_DIR / "saved.json"


def _load() -> Dict[str, Any]:
    if SAVED_PATH.exists():
        try:
            with SAVED_PATH.open("r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}
    return {}


def _save(data: Dict[str, Any]) -> None:
    tmp = SAVED_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(SAVED_PATH)


def list_items() -> List[Dict[str, Any]]:
    db = _load()
    items = db.get("items", [])
    # sort newest saved first
    return list(reversed(items))


def _event_key(e: Dict[str, Any]) -> str:
    # stable key even if provider lacks external_id
    ext = e.get("external_id") or ""
    title = e.get("title") or ""
    start = e.get("start_time") or ""
    venue = e.get("venue_name") or ""
    return f"{ext}|{title}|{start}|{venue}".strip()


def add_item(e: Dict[str, Any]) -> None:
    db = _load()
    items: List[Dict[str, Any]] = db.get("items", [])
    k = _event_key(e)
    # dedupe by key
    if not any(_event_key(x) == k for x in items):
        items.append(e)
        db["items"] = items
        _save(db)


def remove_item(e: Dict[str, Any]) -> None:
    db = _load()
    items: List[Dict[str, Any]] = db.get("items", [])
    k = _event_key(e)
    items = [x for x in items if _event_key(x) != k]
    db["items"] = items
    _save(db)


def clear_all() -> None:
    _save({"items": []})
