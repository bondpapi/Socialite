from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from services import storage

router = APIRouter(prefix="/users", tags=["saved"])


@router.get("/{user_id}/saved")
def list_saved(user_id: str, limit: int = 200) -> Dict[str, Any]:
    items = storage.list_user_saved(user_id, limit=limit)
    return {"user_id": user_id, "count": len(items), "items": items}


@router.post("/{user_id}/saved")
def add_saved(user_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    if not event:
        raise HTTPException(status_code=400, detail="Missing event")
    key = storage.save_user_event(user_id, event)
    return {"ok": True, "event_key": key}


@router.delete("/{user_id}/saved/{event_key}")
def delete_saved(user_id: str, event_key: str) -> Dict[str, Any]:
    storage.remove_user_event(user_id, event_key)
    return {"ok": True}


@router.post("/{user_id}/profile")
def update_profile(user_id: str, display_name: Optional[str] = None) -> Dict[str, Any]:
    storage.upsert_profile(user_id, display_name)
    return {"ok": True, "profile": storage.get_profile(user_id)}
