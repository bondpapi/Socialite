from fastapi import APIRouter, Query
from datetime import datetime, timedelta, timezone
from ..services.aggregator import search_events
from ..services.recommend import rank_events
from ..config import settings

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/search")
async def search(
    city: str | None = None,
    country: str | None = None,
    query: str | None = Query(None, alias="query"),
    days_ahead: int = 60,
    start_in_days: int = 0,
    include_mock: bool = False,   # default: hide mock results
):
    # Calculate start and end dates
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=start_in_days)
    end = start + timedelta(days=days_ahead)

    # Call aggregator
    events = await search_events(city=city, country=country, start=start, end=end, query=query)

    if not include_mock:
        events = [e for e in events if e.get("source") != "mock"]

    passions = ["music", "standup", "marathon", "poetry"]
    ranked = rank_events(events, passions)
    return {"city": city, "country": country, "count": len(ranked), "items": ranked}


@router.get("/providers")
def providers():
    from ..services.aggregator import PROVIDERS
    return {"providers": [p.__class__.__name__ for p in PROVIDERS]}
