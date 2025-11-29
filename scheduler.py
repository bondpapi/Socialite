from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from services import storage
from services.aggregator import search_events


def _tick():
    """
    Very light “scheduler”: every 15 minutes check subscriptions and enqueue digests.
    In production, replace with APScheduler/Celery/Render cron.
    """
    while True:
        try:
            subs = storage.list_subscriptions()
            for sub in subs:
                if not _due_now(sub):  # mini rate-limit by frequency
                    continue

                # Build a digest tailored by prefs
                city = sub.get("home_city") or "Vilnius"
                country = sub.get("home_country") or "LT"

                query = None
                passions = sub.get("passions") or []
                if passions:
                    query = passions[0]

                data = search_events(
                    city=city,
                    country=country,
                    days_ahead=14,
                    start_in_days=0,
                    include_mock=False,
                    query=query,
                )
                items = data.get("items", [])[:10]
                if items:
                    storage.save_digest(sub["user_id"], items)
                    storage.bump_subscription_seen(sub["user_id"])
        except Exception:
            pass

        time.sleep(900)  # 15 minutes


def _due_now(sub: dict) -> bool:
    freq = sub.get("frequency", "weekly")
    last = sub.get("last_sent_at")
    now = datetime.utcnow()
    if last is None:
        return True
    if freq == "daily":
        return (now - last) >= timedelta(days=1)
    return (now - last) >= timedelta(days=7)


def start_background_scheduler():
    t = threading.Thread(target=_tick, daemon=True)
    t.start()
