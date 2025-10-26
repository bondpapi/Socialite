from __future__ import annotations

from fastapi import FastAPI
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

# Routers
app.include_router(events_router.router)
app.include_router(saved_router.router)
app.include_router(metrics_router.router)
app.include_router(agent_router.router)
app.include_router(auth_router.router)
app.include_router(profile_router.router)

# Health (Render warmup hits this)
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"ok": True, "service": "socialite-api"}
