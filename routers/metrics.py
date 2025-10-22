from __future__ import annotations

from fastapi import APIRouter

from services.metrics import summary_http, timeline_http, summary_llm

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/http/summary")
def http_summary():
    return summary_http()


@router.get("/http/timeline")
def http_timeline(last_n: int = 300):
    return {"items": timeline_http(last_n=last_n)}


@router.get("/llm/summary")
def llm_summary():
    return summary_llm()
