"""App settings, loaded from environment variables or a local .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # All optional so the app still starts for local review without secrets.
    # Features that need them check for None and degrade gracefully.
    anthropic_api_key: str | None = None
    dashboard_password: str | None = None
    session_secret: str | None = None

    # Claude settings. Sonnet balances speed and quality for a live demo.
    anthropic_model: str = "claude-sonnet-5-5"
    ai_timeout_seconds: float = 30.0

    # Tenant reports database (reports and inspection statuses). Gitignored.
    app_db_path: str = "data/app.sqlite"
    # Anonymous report form: max submissions per IP per hour.
    reports_per_hour: int = 5
    # Listing checks: max AI-backed (Claude) checks per client per hour. Past the limit the
    # check still runs with the keyword analysis, without calling Claude.
    check_ai_per_hour: int = 20
    # Always mark the town session cookie Secure, e.g. behind a TLS-terminating proxy that
    # uvicorn isn't told about with --proxy-headers.
    force_secure_cookies: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
