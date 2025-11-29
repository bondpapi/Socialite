from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/notify", tags=["notify"])

_notifier = None
try:
    from services import notify as _notifier
except Exception:
    pass


class NotifyRequest(BaseModel):
    user_id: str
    message: str
    channels: Optional[List[str]] = None


@router.post("")
def notify(req: NotifyRequest) -> Dict[str, Any]:
    if _notifier and hasattr(_notifier, "send"):
        try:
            _notifier.send(req.user_id, req.message, req.channels or [])
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": True, "debug": {"notifier": "not_configured"}}
