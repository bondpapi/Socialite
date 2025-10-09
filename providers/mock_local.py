from .base import Provider, EventRecord
from datetime import datetime, timedelta

class MockLocalProvider:
    name = "mock"

    async def search(self, *, city: str, country: str, start=None, end=None, query=None):
        now = datetime.utcnow()
        venue1 = f"{city} Arts Hub"
        venue2 = f"{city} Community Stage"
        venue3 = f"{city} Arena"

        data = [
            EventRecord(
                source=self.name,
                external_id="m1",
                title=f"Indie Night @ {venue1}",
                category="music",
                start_time=now + timedelta(days=2),
                city=city,
                country=country,
                venue_name=venue1,
                min_price=15.0,
                currency="EUR",
                url="https://example.com/indie"
            ),
            EventRecord(
                source=self.name,
                external_id="m2",
                title="Open Mic Poetry",
                category="spoken_word",
                start_time=now + timedelta(days=3),
                city=city,
                country=country,
                venue_name=venue2,
                min_price=0.0,
                currency="EUR",
                url="https://example.com/poetry"
            ),
            EventRecord(
                source=self.name,
                external_id="m3",
                title=f"Home Game: {city} City FC",
                category="sports",
                start_time=now + timedelta(days=6),
                city=city,
                country=country,
                venue_name=venue3,
                min_price=25.0,
                currency="EUR",
                url="https://example.com/fc"
            ),
        ]

        if query:
            q = query.lower()
            data = [d for d in data if q in d["title"].lower() or q in d["category"].lower()]
        return data
