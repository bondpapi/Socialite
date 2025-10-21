from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from middleware import MetricsMiddleware
from routers import (
    events as events_router,
    providers as providers_router,
    saved as saved_router,
    metrics as metrics_router,
    agent as agent_router,
    auth as auth_router,
    profile as profile_router,
)
from scheduler import start_background_scheduler

app = FastAPI(title="Socialite API")

# Register routers (each included once)
app.include_router(events_router.router)
app.include_router(providers_router.router)
app.include_router(saved_router.router)
app.include_router(metrics_router.router)
app.include_router(agent_router.router)
app.include_router(auth_router.router)
app.include_router(profile_router.router)

# CORS + metrics
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(MetricsMiddleware)


@app.on_event("startup")
def _startup():
    # start scheduler if configured; safe to call if it is a no-op
    try:
        start_background_scheduler()
    except Exception:
        # avoid crashing app startup on scheduler issues
        pass


@app.get("/")
def root():
    return {"ok": True, "service": "socialite-api"}
