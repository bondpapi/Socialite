from datetime import date, datetime
from pydantic import BaseModel, Field
from typing import Optional, List


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
    id: Optional[int] = None
    source: str
    external_id: str
    title: str
    category: str
    start_time: Optional[str] = Field(default=None, description="ISO-8601 start time or null")
    city: str
    country: str
    venue_name: Optional[str] = None
    min_price: Optional[float] = None
    currency: Optional[str] = None
    url: Optional[str] = None
