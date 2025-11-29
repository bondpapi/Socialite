from __future__ import annotations

import logging
import time as _t

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from middleware import MetricsMiddleware
from routers import (
    events as events_router,
    saved as saved_router,
    metrics as metrics_router,
    agent as agent_router,
    auth as auth_router,
    profile as profile_router,
)

app = FastAPI(title="socialite-api", version="1.0.0")

# CORS (adjust origins as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Metrics
app.add_middleware(MetricsMiddleware)

_log = logging.getLogger("uvicorn.error")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = _t.perf_counter()  # monotonic for durations
    response = None
    try:
        response = await call_next(request)
        return response
    finally:
        dur_ms = int((_t.perf_counter() - start) * 1000)
        status = getattr(response, "status_code", "-")
        _log.info(
            "path=%s status=%s dur_ms=%s ua=%s",
            request.url.path,
            status,
            dur_ms,
            request.headers.get("user-agent", "-"),
        )

# Routers
app.include_router(events_router.router)
app.include_router(saved_router.router)
app.include_router(metrics_router.router)
app.include_router(agent_router.router)
app.include_router(auth_router.router)
app.include_router(profile_router.router)


@app.get("/ping")
def ping():
    return {"ok": True, "ts": _t.time()}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"ok": True, "service": "socialite-api"}
