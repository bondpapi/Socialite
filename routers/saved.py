from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/saved", tags=["saved"])

_storage = None
try:
    from services import storage as _storage
except Exception:
    pass


class SaveRequest(BaseModel):
    user_id: str
    event: Dict[str, Any]


@router.get("/{user_id}")
def list_saved(user_id: str) -> Dict[str, Any]:
    if _storage and hasattr(_storage, "list_saved"):
        try:
            items = _storage.list_saved(user_id)
            return {"ok": True, "items": items}
        except Exception as e:
            return {"ok": False, "items": [], "error": str(e)}
    return {"ok": True, "items": [], "debug": {"storage": "not_configured"}}


@router.post("")
def save_event(req: SaveRequest) -> Dict[str, Any]:
    if _storage and hasattr(_storage, "save_event"):
        try:
            _storage.save_event(req.user_id, req.event)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": True, "debug": {"storage": "not_configured"}}


@router.delete("/{user_id}")
def clear_saved(user_id: str) -> Dict[str, Any]:
    if _storage and hasattr(_storage, "clear_saved"):
        try:
            _storage.clear_saved(user_id)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": True, "debug": {"storage": "not_configured"}}
