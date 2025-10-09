from fastapi import APIRouter

router = APIRouter(prefix="/notify", tags=["notify"])


@router.get("/ping")
def ping():
    return {"status": "ok"}
