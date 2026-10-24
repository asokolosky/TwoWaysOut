from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import get_app_db, init_db
from app.main import app
from app.routers.check import get_check_limiter
from app.routers.report import get_report_limiter
from app.services.ai_client import get_ai_client
from app.services.boston import get_boston_db
from app.services.rate_limit import RateLimiter


@pytest.fixture
def app_db(tmp_path) -> Path:
    path = tmp_path / "app.sqlite"
    init_db(path)
    return path


@pytest.fixture
def limiter() -> RateLimiter:
    return RateLimiter(limit=5, window_seconds=3600)


@pytest.fixture
def check_limiter() -> RateLimiter:
    return RateLimiter(limit=20, window_seconds=3600)


@pytest.fixture
def client(tmp_path, app_db, limiter, check_limiter):
    # Tests never read the developer's real .env, never call the real Claude API, never read
    # the real Boston database, and never write to the real app database.
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_ai_client] = lambda: None
    app.dependency_overrides[get_boston_db] = lambda: Path(tmp_path / "no-boston-data.sqlite")
    app.dependency_overrides[get_app_db] = lambda: app_db
    app.dependency_overrides[get_report_limiter] = lambda: limiter
    app.dependency_overrides[get_check_limiter] = lambda: check_limiter
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
