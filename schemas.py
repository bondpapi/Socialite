from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    name: str
    email: Optional[str] = None
    birthday: Optional[date] = None
    home_city: Optional[str] = None
    home_country: Optional[str] = None
    passions: List[str] = []  # initial preference seed


class UserOut(BaseModel):
    id: int
    name: str
    birthday: Optional[date] = None
    home_city: Optional[str] = None
    home_country: Optional[str] = None


class EventOut(BaseModel):
    id: Optional[str] = None
    external_id: Optional[str] = None
    source: str
    title: str
    category: Optional[str] = None
    start_time: Optional[str] = Field(
        default=None, description="ISO8601 UTC e.g. 2025-11-05T19:00:00Z"
    )
    city: Optional[str] = None
    country: Optional[str] = None
    venue_name: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    currency: Optional[str] = None
    min_price: Optional[float] = None
