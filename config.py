from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

PKG_DIR = Path(__file__).resolve().parent
ENV_PATH = PKG_DIR / ".env"

try:
    # pydantic v2
    from pydantic_settings import SettingsConfigDict  # type: ignore

    class Settings(BaseSettings):
        # App
        app_env: str = "dev"
        app_timezone: str = "Europe/Vilnius"
        default_country: str = "LT"
        default_city: str = "Vilnius"

        # Discovery
        ics_urls: list[str] = Field(
            default_factory=list, validation_alias="ICS_URLS"
        )
        tavily_api_key: str | None = Field(
            default=None, validation_alias="TAVILY_API_KEY"
        )
        enable_web_discovery: bool = Field(
            False, validation_alias="ENABLE_WEB_DISCOVERY"
        )
        enable_mock_provider: bool = Field(
            True, validation_alias="ENABLE_MOCK_PROVIDER"
        )
        discovery_domains: list[str] = Field(
            default_factory=list, validation_alias="DISCOVERY_DOMAINS"
        )

        # Providers (API keys optional)
        ticketmaster_api_key: str | None = None
        stubhub_api_key: str | None = None
        viagogo_api_key: str | None = None
        google_maps_api_key: str | None = None
        eventbrite_token: str | None = None

        # Features
        enable_translation: bool = True
        enable_presale_tracking: bool = True
        enable_price_compare: bool = True

        # HTTP client (new)
        http_timeout_seconds: float = Field(
            8.0, validation_alias="HTTP_TIMEOUT_SECONDS"
        )
        http_max_retries: int = Field(
            4, validation_alias="HTTP_MAX_RETRIES"
        )

        model_config = SettingsConfigDict(
            env_file=str(ENV_PATH),
            env_file_encoding="utf-8",
            extra="ignore",
        )

except Exception:
    class Settings(BaseSettings):
        app_env: str = "dev"
        app_timezone: str = "Europe/Vilnius"
        default_country: str = "LT"
        default_city: str = "Vilnius"

        ics_urls: list[str] = Field(default_factory=list)
        tavily_api_key: str | None = None
        enable_web_discovery: bool = Field(False)
        enable_mock_provider: bool = Field(True)
        discovery_domains: list[str] = Field(default_factory=list)

        ticketmaster_api_key: str | None = None
        stubhub_api_key: str | None = None
        viagogo_api_key: str | None = None
        google_maps_api_key: str | None = None
        eventbrite_token: str | None = None

        enable_translation: bool = True
        enable_presale_tracking: bool = True
        enable_price_compare: bool = True

        # HTTP client (new)
        http_timeout_seconds: float = 8.0
        http_max_retries: int = 4

        class Config:
            env_file = str(ENV_PATH)
            env_file_encoding = "utf-8"
            extra = "ignore"


settings = Settings()
