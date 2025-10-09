# social_agent_ai/config.py
from __future__ import annotations

import json
import ast
from pathlib import Path
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PKG_DIR = Path(__file__).resolve().parent
ENV_PATH = PKG_DIR / ".env"


def _parse_list(v) -> list[str]:
    """Accept JSON list, Python list literal, or comma-separated string."""
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return []
        # Try JSON
        try:
            data = json.loads(s)
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
        except Exception:
            pass
        # Try Python literal
        try:
            data = ast.literal_eval(s)
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
        except Exception:
            pass
        # Fallback: comma-separated
        return [p.strip() for p in s.split(",") if p.strip()]
    # Unknown type -> empty
    return []


class Settings(BaseSettings):
    # Tell pydantic where to read .env and to be lax about extra/case
    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,  # allow upper/lower env names
    )

    # ---- App basics ---------------------------------------------------------
    app_name: str = Field("Socialite", validation_alias="APP_NAME")
    app_env: str = Field(default="dev", alias="APP_ENV")
    app_timezone: str = Field(default="Europe/Vilnius", alias="APP_TIMEZONE")
    default_country: str = Field(default="LT", alias="DEFAULT_COUNTRY")
    default_city: str = Field(default="Vilnius", alias="DEFAULT_CITY")

    # ---- Feature flags ------------------------------------------------------
    enable_web_discovery: bool = Field(default=False, alias="ENABLE_WEB_DISCOVERY")
    enable_mock_provider: bool = Field(default=True, alias="ENABLE_MOCK_PROVIDER")
    enable_translation: bool = Field(default=True, alias="ENABLE_TRANSLATION")
    enable_presale_tracking: bool = Field(default=True, alias="ENABLE_PRESALE_TRACKING")
    enable_price_compare: bool = Field(default=True, alias="ENABLE_PRICE_COMPARE")

    # ---- Web Discovery / Tavily --------------------------------------------
    tavily_api_key: Optional[str] = Field(default=None, alias="TAVILY_API_KEY")
    discovery_domains: list[str] = Field(default_factory=list, alias="DISCOVERY_DOMAINS")

    # ---- Optional ICS calendar feeds ---------------------------------------
    ics_urls: list[str] = Field(default_factory=list, alias="ICS_URLS")

    # ---- Provider keys/tokens ----------------------------------------------
    ticketmaster_api_key: Optional[str] = Field(default=None, alias="TICKETMASTER_API_KEY")
    eventbrite_token: Optional[str] = Field(default=None, alias="EVENTBRITE_TOKEN")
    stubhub_api_key: Optional[str] = Field(default=None, alias="STUBHUB_API_KEY")
    seatgeek_client_id: Optional[str] = Field(default=None, alias="SEATGEEK_CLIENT_ID")
    seatgeek_client_secret: Optional[str] = Field(default=None, alias="SEATGEEK_CLIENT_SECRET")
    viagogo_api_key: Optional[str] = Field(default=None, alias="VIAGOGO_API_KEY")
    google_maps_api_key: Optional[str] = Field(default=None, alias="GOOGLE_MAPS_API_KEY")

    # ---- Coercion for list-like env vars -----------------------------------
    @field_validator("discovery_domains", "ics_urls", mode="before")
    @classmethod
    def _coerce_list(cls, v):
        return _parse_list(v)
class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

# (Optional) quick debug aid:
# Uncomment to see whether the Tavily key is loaded and lists parsed.
# print(
#     "[config]",
#     "env:", settings.app_env,
#     "| web_discovery:", settings.enable_web_discovery,
#     "| tavily:", bool(settings.tavily_api_key),
#     "| domains:", settings.discovery_domains,
#     "| ics:", settings.ics_urls,
# )
