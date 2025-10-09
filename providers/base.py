from __future__ import annotations
from typing import Protocol, Iterable
from datetime import datetime


class EventRecord(dict):
    """Normalized dict for events produced by providers."""
    pass


class Provider(Protocol):
    name: str

    async def search(
        self,
        *,
        city: str,
        country: str,
        start: datetime | None = None,
        end: datetime | None = None,
        query: str | None = None
    ) -> Iterable[EventRecord]:
        ...
