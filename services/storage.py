from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from social_agent_ai.db import (
    init_db,
    upsert_user,
    get_user,
    save_event,
    delete_event,
    list_saved,
)

init_db()


def event_key(event: Dict[str, Any]) -> str:
    """
    Stable key from source + external_id or url + title as fallback.
    """
    src = str(event.get("source") or "")
    ext = str(event.get("external_id") or "")
    url = str(event.get("url") or "")
    title = str(event.get("title") or "")
    base = f"{src}::{ext}::{url}::{title}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def upsert_profile(user_id: str, display_name: Optional[str]) -> None:
    upsert_user(user_id, display_name)


def get_profile(user_id: str) -> Dict[str, Any]:
    return get_user(user_id) or {"user_id": user_id, "display_name": None}


def save_user_event(user_id: str, event: Dict[str, Any]) -> str:
    key = event_key(event)
    save_event(user_id, key, event)
    return key


def remove_user_event(user_id: str, event_key: str) -> None:
    delete_event(user_id, event_key)


def list_user_saved(user_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    return list_saved(user_id, limit=limit)
