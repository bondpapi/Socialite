from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: Optional[str] = None
    birthday: Optional[date] = None
    home_city: Optional[str] = None
    home_country: Optional[str] = None


class Venue(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    city: str
    country: str
    address: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


class Event(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source: str
    external_id: str
    title: str
    category: str  # music/comedy/sports/movies/etc
    start_time: datetime
    end_time: Optional[datetime] = None
    city: str
    country: str
    venue_name: Optional[str] = None
    language: Optional[str] = None
    min_price: Optional[float] = None
    currency: Optional[str] = None
    age_restriction: Optional[int] = None
    url: Optional[str] = None


class Preference(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    tag: str  # e.g., "indie-rock", "standup", "marathon"
    weight: float = 1.0  # simple weighting for ranker


class Watchlist(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    event_id: int
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Alert(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    event_id: Optional[int] = None
    kind: str  # price_drop, presale_open, new_match, birthday
    created_at: datetime = Field(default_factory=datetime.utcnow)
