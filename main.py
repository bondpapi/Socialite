from fastapi import FastAPI
from .db import init_db
from .routers import events, profile, notify

app = FastAPI(title="Socialite", version="0.1.0")


@app.on_event("startup")
def startup():
    init_db()


app.include_router(profile.router)
app.include_router(events.router)
app.include_router(notify.router)


@app.get("/")
def root():
    return {"hello": "social-agent-ai"}
