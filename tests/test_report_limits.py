"""Report rate limit refunds on rejected submissions, and explicit SQLite connection closing."""
import sqlite3

import pytest

from app.main import app
from app.services import reports
from app.services.boston import get_boston_db
from tests.fixtures.boston_db import build_fixture_db


@pytest.fixture(scope="module")
def boston_db(tmp_path_factory):
    return build_fixture_db(tmp_path_factory.mktemp("bos") / "boston.sqlite")


@pytest.fixture
def with_boston(client, boston_db):
    app.dependency_overrides[get_boston_db] = lambda: boston_db
    return client


GOOD = {"address": "182 London St, East Boston 02128", "category": "smoke_alarm"}


def count(app_db):
    with sqlite3.connect(app_db) as con:
        return con.execute("SELECT COUNT(*) FROM reports").fetchone()[0]


def test_rejected_submissions_do_not_use_up_the_limit(with_boston, app_db, limiter):
    # Many invalid submissions in a row (no street number, unknown category, contact info).
    bad = [
        {**GOOD, "address": "London St"},
        {**GOOD, "category": "not_a_category"},
        {**GOOD, "address": "call me at 617-555-0123"},
    ]
    for _ in range(3):
        for data in bad:
            resp = with_boston.post("/report", data=data)
            assert resp.status_code == 422
            assert "try again later" not in resp.text
    assert count(app_db) == 0
    # The full hourly allowance is still there for real reports.
    for _ in range(limiter.limit):
        assert with_boston.post("/report", data=GOOD).status_code == 200
    resp = with_boston.post("/report", data=GOOD)
    assert resp.status_code == 429
    assert count(app_db) == limiter.limit


def test_limit_still_applies_to_rejected_submissions_once_reached(with_boston, app_db, limiter):
    for _ in range(limiter.limit):
        assert with_boston.post("/report", data=GOOD).status_code == 200
    # At the limit, even an invalid submission gets the 429, before any validation.
    resp = with_boston.post("/report", data={**GOOD, "address": "London St"})
    assert resp.status_code == 429


class _Tracked(sqlite3.Connection):
    opened: list["_Tracked"] = []

    def __init__(self, database, *args, **kwargs):
        super().__init__(database, *args, **kwargs)
        self.database = str(database)
        self.is_closed = False
        _Tracked.opened.append(self)

    def close(self):
        self.is_closed = True
        super().close()


@pytest.fixture
def tracked(monkeypatch):
    real = sqlite3.connect
    _Tracked.opened = []
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: real(*a, factory=_Tracked, **k))
    return _Tracked.opened


def test_save_and_count_close_their_connections(app_db, boston_db, tracked):
    assert reports.save_report(app_db, boston_db, address=GOOD["address"], category="smoke_alarm").id
    assert reports.count_reports(app_db) == 1
    assert reports.count_reports(app_db, simulated=False) == 1
    app_conns = [c for c in tracked if c.database == str(app_db)]
    assert len(app_conns) == 3
    assert all(c.is_closed for c in app_conns)


def test_saved_report_is_committed(app_db, boston_db):
    reports.save_report(app_db, boston_db, address=GOOD["address"], category="smoke_alarm")
    # A fresh connection sees the row, so the insert was committed before closing.
    assert count(app_db) == 1
