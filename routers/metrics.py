from __future__ import annotations

from fastapi import APIRouter
from typing import Dict, Any

router = APIRouter(prefix="/metrics", tags=["metrics"])

# If you have a middleware or service exposing counters, you can import it here.
_metrics_impl = None
try:
    from services import metrics as _metrics_impl  # optional
except Exception:
    pass


@router.get("")
def get_metrics() -> Dict[str, Any]:
    if _metrics_impl and hasattr(_metrics_impl, "snapshot"):
        try:
            return {"ok": True, "metrics": _metrics_impl.snapshot()}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    # Safe default so /metrics never 500s
    return {"ok": True, "metrics": {"status": "up"}}
