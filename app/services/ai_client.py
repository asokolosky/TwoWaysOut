"""Creates the Anthropic client from settings. Returns None when no API key is set."""

from functools import lru_cache

from fastapi import Depends

from app.config import Settings, get_settings


@lru_cache(maxsize=4)
def _client_for(api_key: str):
    import anthropic

    # The SDK retries connection errors and 429/5xx once; the analyzer handles the rest.
    return anthropic.Anthropic(api_key=api_key, max_retries=1)


def get_ai_client(settings: Settings = Depends(get_settings)):
    if not settings.anthropic_api_key:
        return None
    return _client_for(settings.anthropic_api_key)
