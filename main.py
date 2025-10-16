from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from social_agent_ai.middleware import MetricsMiddleware
from social_agent_ai.routers import events, providers
from social_agent_ai.routers import saved as saved_router
from social_agent_ai.routers import metrics as metrics_router

app = FastAPI(title="Socialite API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)
app.add_middleware(MetricsMiddleware)

app.include_router(events.router)
app.include_router(providers.router)
app.include_router(saved_router.router)
app.include_router(metrics_router.router)


@app.get("/")
def root():
    return {"ok": True, "service": "socialite-api"}
