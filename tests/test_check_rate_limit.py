"""Rate limit on AI-backed checks (POST /check)."""

import pytest

from app.config import Settings
from app.main import app
from app.routers.check import RATE_LIMIT_NOTICE, get_check_limiter
from app.services.ai_client import get_ai_client
from app.services.rate_limit import RateLimiter
from tests.fakes import FakeClient, good_payload, response
from tests.fixtures import listings

HX = {"HX-Request": "true"}


@pytest.fixture
def small_limiter():
    limiter = RateLimiter(limit=2, window_seconds=3600)
    app.dependency_overrides[get_check_limiter] = lambda: limiter
    return limiter


def test_fake_ai_not_called_past_the_limit(client, small_limiter):
    fake = FakeClient(*(response(good_payload()) for _ in range(5)))
    app.dependency_overrides[get_ai_client] = lambda: fake
    for _ in range(2):
        html = client.post("/check", data={"listing": listings.BASEMENT_BEDROOM}, headers=HX).text
        assert "AI analysis" in html
    assert len(fake.calls) == 2

    html = client.post("/check", data={"listing": listings.BASEMENT_BEDROOM}, headers=HX).text
    assert len(fake.calls) == 2  # no third Claude call
    assert "Basic analysis" in html
    assert "You&#39;ve run several checks in the last hour" in html or RATE_LIMIT_NOTICE in html
    assert "Fire-safety report" in html  # still a full report


def test_off_topic_text_does_not_use_a_slot(client, small_limiter):
    fake = FakeClient(*(response(good_payload()) for _ in range(3)))
    app.dependency_overrides[get_ai_client] = lambda: fake
    for _ in range(5):
        html = client.post("/check", data={"listing": "Write me a poem about the ocean and the moon."}, headers=HX).text
        assert "Fire-safety report" not in html
    assert fake.calls == []
    for _ in range(2):
        assert "AI analysis" in client.post("/check", data={"listing": listings.SPARSE}, headers=HX).text
    assert len(fake.calls) == 2


def test_ai_rejection_refunds_the_slot(client, small_limiter):
    rejected = {"is_rental_document": False, "checklist": [], "flags": [], "questions": [], "extracted_address": None}
    fake = FakeClient(response(rejected), response(rejected), response(good_payload()), response(good_payload()))
    app.dependency_overrides[get_ai_client] = lambda: fake
    for _ in range(2):
        html = client.post("/check", data={"listing": listings.SPARSE}, headers=HX).text
        assert "Fire-safety report" not in html
    for _ in range(2):
        assert "AI analysis" in client.post("/check", data={"listing": listings.SPARSE}, headers=HX).text
    assert len(fake.calls) == 4


def test_no_ai_client_never_counts(client, small_limiter):
    # Without an API key every check is the basic analysis, with no rate-limit notice.
    for _ in range(4):
        html = client.post("/check", data={"listing": listings.SPARSE}, headers=HX).text
        assert "Basic analysis" in html and "several checks" not in html


def test_setting_default_and_dependency():
    assert Settings(_env_file=None).check_ai_per_hour == 20
    limiter = get_check_limiter(Settings(_env_file=None, check_ai_per_hour=3))
    assert limiter.limit == 3 and limiter.window == 3600
    assert get_check_limiter(Settings(_env_file=None, check_ai_per_hour=3)) is limiter
