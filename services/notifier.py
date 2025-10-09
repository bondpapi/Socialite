from apscheduler.schedulers.asyncio import AsyncIOScheduler
from ..config import settings
from .aggregator import search_events
from .recommend import rank_events

scheduler = AsyncIOScheduler(timezone=settings.app_timezone)

async def daily_digest_job():
    events = await search_events(city=settings.default_city, country=settings.default_country)
    ranked = rank_events(events, ["music","standup","poetry","football"])
    top = ranked[:5]
    # For now we just log; later: email/push/webhook
    print("[Daily Digest]", [e["title"] for e in top])

def start_scheduler():
    scheduler.add_job(daily_digest_job, "cron", hour=9, minute=0)
    scheduler.start()
