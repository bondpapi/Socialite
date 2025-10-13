from fastapi import FastAPI
from .db import init_db
from .routers import events, profile, notify
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Socialite", version="0.1.0")

# allow your Streamlit app (or temporarily "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],            # or ["https://your-streamlit-app.streamlit.app"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


app.include_router(profile.router)
app.include_router(events.router)
app.include_router(notify.router)


@app.get("/")
def root():
    return {"hello": "social-agent-ai"}
