from fastapi import APIRouter
from ..schemas import UserCreate

router = APIRouter(prefix="/profile", tags=["profile"])

# In-memory demo (wire to DB later)
USER = {"id": 1, "name": "You", "passions": ["music", "standup", "marathon"]}


@router.post("/setup")
def setup(user: UserCreate):
    global USER
    USER = {
        "id": 1,
        "name": user.name,
        "birthday": user.birthday,
        "home_city": user.home_city,
        "home_country": user.home_country,
        "passions": user.passions,
    }
    return {"ok": True, "user": USER}


@router.get("/me")
def me():
    return USER
