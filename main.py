from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from social_agent_ai.routers import events, providers
from social_agent_ai.routers import saved as saved_router  # NEW

app = FastAPI(title="Socialite API")

# CORS for local UI and cloud UIs
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Existing endpoints
app.include_router(events.router)
app.include_router(providers.router)
# NEW: saved items
app.include_router(saved_router.router)


@app.get("/")
def root():
    return {"ok": True, "service": "socialite-api"}
