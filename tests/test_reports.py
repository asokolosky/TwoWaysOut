import sqlite3
from datetime import date, timedelta

import pytest

from app.content.copy import DISCLAIMER
from app.main import app
from app.services.boston import get_boston_db
from app.services.rate_limit import RateLimiter
from app.services.reports import ReportError, redact_contact_info, save_report
from tests.fixtures.boston_db import build_fixture_db
from tests.fixtures.listings import SPARSE


@pytest.fixture(scope="module")
def boston_db(tmp_path_factory):
    return build_fixture_db(tmp_path_factory.mktemp("bos") / "boston.sqlite")


@pytest.fixture
def with_boston(client, boston_db):
    app.dependency_overrides[get_boston_db] = lambda: boston_db
    return client


def rows(app_db):
    with sqlite3.connect(app_db) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute("SELECT * FROM reports ORDER BY id")]


def submit(client, **fields):
    data = {"address": "182 London St, East Boston 02128", "category": "smoke_alarm", **fields}
    return client.post("/report", data=data)


# --- Form ---------------------------------------------------------------------------------

def test_form_renders_with_categories_and_911(client):
    html = client.get("/report").text
    assert "No second way out" in html
    assert "Missing or broken smoke or carbon monoxide alarm" in html
    assert "call 911" in html
    assert '<legend class="font-medium">What&#39;s the problem?</legend>' in html or "What's the problem?" in html
    assert 'name="website"' in html  # honeypot present
    # No contact fields.
    for field in ('name="email"', 'name="phone"', 'name="name"'):
        assert field not in html


def test_form_prefills_address(client):
    html = client.get("/report", params={"address": "41 Parker Hill Ave, Boston"}).text
    assert 'value="41 Parker Hill Ave, Boston"' in html


def test_prefilled_address_is_escaped_and_capped(client):
    evil = '"><script>alert(1)</script>' + "A" * 500
    html = client.get("/report", params={"address": evil}).text
    assert "<script>alert(1)" not in html
    assert "&#34;&gt;&lt;script&gt;" in html or "&quot;&gt;&lt;script&gt;" in html
    assert "A" * 200 not in html  # capped at 200 chars including the prefix
    assert "A" * (200 - len(evil[: evil.index("A")]) - 1) in html


def test_student_report_links_to_prefilled_form(client):
    html = client.post("/check", data={"listing": SPARSE, "address": "182 London St 02128"}, headers={"HX-Request": "true"}).text
    assert 'href="/report?address=182%20London%20St%2002128"' in html
    assert "Report a problem here" in html


# --- Saving -------------------------------------------------------------------------------

def test_valid_report_saved_and_matched(with_boston, app_db):
    resp = submit(with_boston, description="Alarm in the hallway was removed.", observed_date="2026-10-01")
    assert resp.status_code == 200
    assert "your report was received" in resp.text
    assert "182 London St, East Boston 02128" in resp.text
    assert "Boston 311" in resp.text
    assert DISCLAIMER in resp.text
    [r] = rows(app_db)
    assert r["parcel_id"] == "0106069000" and r["sam_id"] == "1" and r["ward"] == 1
    assert r["address_key"] == "PARCEL 0106069000"
    assert r["category"] == "smoke_alarm" and r["status"] == "open"
    assert r["observed_date"] == "2026-10-01"
    assert r["is_simulated"] == 0


def test_unit_numbers_group_to_same_building(with_boston, app_db):
    submit(with_boston, address="182 London St Apt 3, East Boston 02128")
    submit(with_boston, address="182 london street #1 02128", category="blocked_exit")
    keys = {r["address_key"] for r in rows(app_db)}
    assert keys == {"PARCEL 0106069000"}


def test_outside_boston_saved_unmatched(with_boston, app_db):
    resp = submit(with_boston, address="12 Example St, Amherst, MA 01002", category="no_second_exit")
    assert resp.status_code == 200
    assert "Board of Health" in resp.text
    assert "Boston 311" not in resp.text
    [r] = rows(app_db)
    assert r["parcel_id"] is None
    assert r["address_key"] == "12 EXAMPLE ST 01002"
    assert r["zip"] == "01002"


def test_user_submissions_are_never_simulated(with_boston, app_db):
    # Even if someone adds the field to the form.
    with_boston.post("/report", data={"address": "182 London St 02128", "category": "other", "is_simulated": "1"})
    assert [r["is_simulated"] for r in rows(app_db)] == [0]


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"address": ""}, "Enter the address"),
        ({"address": "London St"}, "street number"),
        ({"category": "aliens"}, "Choose what kind of problem"),
        ({"category": ""}, "Choose what kind of problem"),
        ({"description": "x" * 1001}, "under 1,000 characters"),
        ({"description": "x" * 5000}, "under 1,000 characters"),
        ({"address": "1 " + "Long " * 100 + "St"}, "too long"),
        ({"observed_date": "next tuesday"}, "YYYY-MM-DD"),
        ({"observed_date": (date.today() + timedelta(days=2)).isoformat()}, "can&#39;t be in the future"),
        ({"observed_date": "1990-01-01"}, "too far in the past"),
    ],
)
def test_invalid_input_rejected(with_boston, app_db, fields, message):
    resp = submit(with_boston, **fields)
    assert resp.status_code == 422
    assert 'role="alert"' in resp.text and message in resp.text
    assert rows(app_db) == []


def test_invalid_input_keeps_what_was_typed(with_boston):
    html = submit(with_boston, category="nope", description="Back stairs are blocked").text
    assert "Back stairs are blocked" in html
    assert 'value="182 London St, East Boston 02128"' in html


def test_description_is_escaped(with_boston, app_db):
    html = submit(with_boston, category="nope", description='<script>alert("x")</script>').text
    assert "<script>alert" not in html and "&lt;script&gt;" in html


def test_contact_info_removed(with_boston, app_db):
    resp = submit(with_boston, description="Call me at (617) 555-0123 or email tenant@example.com about the alarm.")
    assert "removed contact information" in resp.text
    [r] = rows(app_db)
    assert "555" not in r["description"] and "example.com" not in r["description"]
    assert "[phone removed]" in r["description"] and "[email removed]" in r["description"]


def test_honeypot_shows_thanks_but_saves_nothing(with_boston, app_db):
    resp = submit(with_boston, website="http://spam.example")
    assert resp.status_code == 200 and "your report was received" in resp.text
    assert rows(app_db) == []


def test_rate_limit(with_boston, app_db, limiter):
    for _ in range(5):
        assert submit(with_boston).status_code == 200
    resp = submit(with_boston)
    assert resp.status_code == 429
    assert "try again later" in resp.text
    assert len(rows(app_db)) == 5


def test_rate_limiter_window():
    now = [0.0]
    rl = RateLimiter(limit=2, window_seconds=60, clock=lambda: now[0])
    assert rl.allow("a") and rl.allow("a") and not rl.allow("a")
    assert rl.allow("b")  # separate key
    now[0] = 61
    assert rl.allow("a")


def test_rate_limiter_sweeps_expired_keys():
    now = [0.0]
    rl = RateLimiter(limit=2, window_seconds=60, clock=lambda: now[0])
    rl.allow("1.1.1.1")
    now[0] = 30
    rl.allow("2.2.2.2")
    now[0] = 61
    rl.sweep()
    assert len(rl._hits) == 1  # only the visitor still inside the window
    now[0] = 200
    rl.sweep()
    assert rl._hits == {}


def test_rate_limiter_sweeps_periodically_on_allow():
    from app.services import rate_limit

    now = [0.0]
    rl = RateLimiter(limit=2, window_seconds=60, clock=lambda: now[0])
    for i in range(10):
        rl.allow(f"10.0.0.{i}")
    now[0] = 1000
    for _ in range(rate_limit.SWEEP_EVERY_CALLS):
        rl.allow("10.9.9.9")
    assert len(rl._hits) == 1


def test_rate_limiter_does_not_hold_raw_ips():
    rl = RateLimiter(limit=2, window_seconds=60)
    rl.allow("203.0.113.7")
    assert "203.0.113.7" not in rl._hits
    assert not any("203.0.113.7" in k for k in rl._hits)
    # Different limiters use different salts.
    other = RateLimiter(limit=2, window_seconds=60)
    other.allow("203.0.113.7")
    assert set(rl._hits) != set(other._hits)


def test_created_at_is_day_precision(with_boston, app_db):
    import re

    submit(with_boston)
    [r] = rows(app_db)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["created_at"])


@pytest.mark.parametrize(
    "address",
    [
        "182 London St, call 617-555-0123",
        "182 London St jane@umass.edu",
        "182 London St, jane at umass dot edu",
        "182 London St 555-1234",
    ],
)
def test_address_with_contact_info_rejected(with_boston, app_db, address):
    resp = submit(with_boston, address=address)
    assert resp.status_code == 422
    assert "Leave contact information out of the address." in resp.text
    assert rows(app_db) == []


def test_address_with_contact_info_rejected_without_http(tmp_path, boston_db):
    from app.db import init_db

    db = tmp_path / "a.sqlite"
    init_db(db)
    with pytest.raises(ReportError, match="Leave contact information out of the address."):
        save_report(db, boston_db, address="182 London St (617) 555-0123", category="other")


def test_ip_not_stored(with_boston, app_db):
    submit(with_boston)
    with sqlite3.connect(app_db) as con:
        cols = [r[1] for r in con.execute("PRAGMA table_info(reports)")]
    assert not {"ip", "client_ip", "email", "phone", "name"} & set(cols)
    assert "testclient" not in str(rows(app_db))


# --- Unit tests ---------------------------------------------------------------------------

def test_redact_contact_info():
    text, changed = redact_contact_info("Text 617.555.0199, +1 413 555 0100, or a.b+c@uni.edu")
    assert changed and "555" not in text and "@" not in text
    assert redact_contact_info("Alarm missing on floor 3 since 2024") == ("Alarm missing on floor 3 since 2024", False)


@pytest.mark.parametrize(
    "text, secret, label",
    [
        ("Email jane @ umass.edu about it", "umass", "[email removed]"),
        ("Email jane@ umass.edu", "umass", "[email removed]"),
        ("Write jane at umass dot edu", "umass", "[email removed]"),
        ("Write jane [at] umass [dot] edu", "umass", "[email removed]"),
        ("Write jane.doe AT mail DOT umass DOT edu", "umass", "[email removed]"),
        ("Call 617 - 555 - 1234", "555", "[phone removed]"),
        ("Call 617 . 555 . 1234", "555", "[phone removed]"),
        ("Call 617/555-1234", "555", "[phone removed]"),
        ("Call (617) 555-0123", "555", "[phone removed]"),
        ("Call 555-1234 after 5", "1234", "[phone removed]"),
        ("Call 555 - 1234", "1234", "[phone removed]"),
        ("Call 555.1234", "1234", "[phone removed]"),
        ("Call +44 20 7946 0958", "7946", "[phone removed]"),
        ("Call +1 413 555 0100", "555", "[phone removed]"),
        ("DM @jane_doe on Instagram", "jane_doe", "[handle removed]"),
    ],
)
def test_redact_contact_info_variants(text, secret, label):
    cleaned, changed = redact_contact_info(text)
    assert changed
    assert secret not in cleaned
    assert label in cleaned


@pytest.mark.parametrize(
    "text",
    [
        "Alarm missing on floor 3 since 2024",
        "Unit 12, 3rd floor",
        "182 London St",
        "built in 1910",
        "Noticed on 2026-10-01",
        "182 London St, East Boston 02128",
        "Rent is 1500 per month for 2 units",
        "Look at the alarm at the front door",
        "Floors 1-3, between 2024 and 2025",
        "12-14 Example St",
        "ZIP 02128-1234",
    ],
)
def test_redact_contact_info_leaves_ordinary_text(text):
    assert redact_contact_info(text) == (text, False)


def test_save_report_validates_without_http(tmp_path, boston_db):
    from app.db import init_db

    db = tmp_path / "a.sqlite"
    init_db(db)
    with pytest.raises(ReportError):
        save_report(db, boston_db, address="182 London St", category="bogus")


def test_save_report_sets_created_at_explicitly_even_with_timestamp_default(tmp_path, boston_db):
    # An older table whose created_at default is a full timestamp: save_report must still
    # store day precision only.
    db = tmp_path / "old.sqlite"
    from app.db import SCHEMA

    with sqlite3.connect(db) as con:
        con.executescript(SCHEMA.replace("strftime('%Y-%m-%d', 'now')", "CURRENT_TIMESTAMP"))
    save_report(db, boston_db, address="12 Example St Apt 3R, Amherst 01002", category="other")
    [r] = rows(db)
    assert r["created_at"] == date.today().isoformat()
    assert len(r["created_at"]) == 10


def test_text_key_drops_unit_and_free_text():
    from app.services.reports import text_key

    assert text_key("12 Example St Apt 3R, Amherst 01002") == "12 EXAMPLE ST 01002"
    assert text_key("12 Example St #3R, Amherst") == "12 EXAMPLE ST AMHERST"
    assert text_key("behind the blue house") is None
