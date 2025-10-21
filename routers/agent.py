from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agent import run_agent
from ..services import storage

router = APIRouter(prefix="/agent", tags=["agent"])


class ChatIn(BaseModel):
    user_id: str
    message: str


class ChatOut(BaseModel):
    reply: str
    used_tools: list[str]


@router.post("/chat", response_model=ChatOut)
def chat(payload: ChatIn) -> ChatOut:
    try:
        turn = run_agent(payload.user_id, payload.message)
        return ChatOut(reply=turn.reply, used_tools=turn.used_tools)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"agent.chat failed: {exc!r}")


@router.get("/digest/{user_id}")
def get_pending_digest(user_id: str) -> dict:
    """
    Simple pull-based digest store (for Streamlit to fetch).
    Your scheduler writes digests to storage.save_digest(user_id, items=[...]).
    """
    digest = storage.pop_digest(user_id)  # returns and clears pending
    return {"items": digest or []}
