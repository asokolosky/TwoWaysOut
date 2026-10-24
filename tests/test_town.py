"""Town dashboard: auth, CSRF, real vs simulated separation, filters, detail, and status."""
import html
import re
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.content.copy import RANKING_STATEMENT
from app.content.report_categories import REPORT_CATEGORIES
from app.main import app
from app.routers.town import get_login_limiter
from app.services import town_auth
from app.services.boston import get_boston_db
from app.services.building_status import get_status
from app.services.ranking import rank_real_buildings
from app.services.rate_limit import RateLimiter
from app.services.reports import text_key
from tests.fixtures.boston_db import build_fixture_db

PASSWORD = "test-pass"
SECRET = "x" * 40
LONDON = "0106069000"  # likely rental with official records
OAK_DORCHESTER = "1500001000"  # owner-occupied single family: not a rental
APT_ADDRESS = "12 Fake St Apt 3R, Boston MA 02128"
APT_KEY = text_key(APT_ADDRESS)  # "12 FAKE ST 02128"
ELM_KEY = "5 ELM ST 02134"
CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')
KEY_RE = re.compile(r'data-building-key="([^"]+)"')


@pytest.fixture(scope="module")
def boston_db(tmp_path_factory):
    return build_fixture_db(tmp_path_factory.mktemp("boston") / "boston.sqlite")


@pytest.fixture
def town_limiter():
    return RateLimiter(limit=5, window_seconds=900)


@pytest.fixture
def town(client, app_db, boston_db, town_limiter):
    """The conftest client with the dashboard configured and the fixture Boston DB."""
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, dashboard_password=PASSWORD, session_secret=SECRET
    )
    app.dependency_overrides[get_boston_db] = lambda: boston_db
    app.dependency_overrides[get_login_limiter] = lambda: town_limiter
    return client


def add_report(app_db, *, key, address, category="other", extra=None, parcel=None, zip_code=None,
               observed=None, created="2026-10-20", description=None):
    with sqlite3.connect(app_db) as con:
        con.execute(
            """INSERT INTO reports (address_input, address_key, parcel_id, zip, category, extra_categories,
                                    description, observed_date, created_at, is_simulated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (address, key, parcel, zip_code, category, extra, description, observed, created),
        )


def add_simulated(app_db, n=40):
    cats = list(REPORT_CATEGORIES)
    with sqlite3.connect(app_db) as con:
        for i in range(n):
            con.execute(
                """INSERT INTO simulated_reports (sim_building, ward, rental_type, category, description,
                                                  observed_date, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (f"SIM-{i % 8:02d}", 21, "3-family", cats[i % len(cats)], "Fictional smoke alarm story",
                 "2026-10-01", "2026-10-02"),
            )


@pytest.fixture
def seeded(app_db):
    add_report(app_db, key=APT_KEY, address=APT_ADDRESS, category="smoke_alarm", extra="blocked_exit",
               zip_code="02128", observed="2026-09-15", created="2026-09-20",
               description="Alarm in the hallway was removed.")
    add_report(app_db, key=ELM_KEY, address="5 Elm St, Unit 9Q 02134", category="heating_hazard", zip_code="02134")
    add_report(app_db, key=f"PARCEL {OAK_DORCHESTER}", address="10 Oak Ave Dorchester 02122",
               parcel=OAK_DORCHESTER, category="electrical_hazard", zip_code="02122")
    add_report(app_db, key=f"PARCEL {LONDON}", address="182 London St #2 02128", parcel=LONDON,
               category="no_second_exit", zip_code="02128")
    add_simulated(app_db)
    return app_db


def login(c, password=PASSWORD):
    return c.post("/town/login", data={"password": password}, follow_redirects=False)


def csrf_from(html):
    m = CSRF_RE.search(html)
    assert m, "page has no CSRF token"
    return m.group(1)


def main_of(page):
    """The <main> content (the <head> has SRI hashes that can contain any short string)."""
    return page[page.index("<main") :]


def real_table(html):
    start = html.index('class="data-table town-table')
    return html[start : html.index("</table>", start)]


def sim_section(html):
    start = html.index('id="sim-heading"')
    return html[start : html.index('id="how-heading"')]


# --- Configuration and auth ---------------------------------------------------------------


@pytest.mark.parametrize(
    "settings",
    [
        Settings(_env_file=None),
        Settings(_env_file=None, dashboard_password=PASSWORD),
        Settings(_env_file=None, session_secret=SECRET),
        Settings(_env_file=None, dashboard_password=PASSWORD, session_secret="short"),
    ],
)
def test_not_configured_is_closed(client, settings):
    app.dependency_overrides[get_settings] = lambda: settings
    for path in ("/town", "/town/login", "/town/building?key=x"):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 503
        assert "Dashboard isn't configured" in resp.text
        assert ".env.example" in resp.text
    resp = client.post("/town/login", data={"password": ""}, follow_redirects=False)
    assert resp.status_code == 503
    assert town_auth.SESSION_COOKIE not in resp.headers.get("set-cookie", "")


def test_unauthenticated_redirects(town):
    for path in ("/town", "/town/building?key=x", "/town/simulated/SIM-00"):
        resp = town.get(path, follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/town/login"


def test_unauthenticated_htmx_gets_hx_redirect(town):
    resp = town.get("/town", headers={"HX-Request": "true", "HX-Target": "town-results"}, follow_redirects=False)
    assert resp.headers["HX-Redirect"] == "/town/login"
    assert "town-table" not in resp.text


def test_login_form_is_accessible(town):
    html = town.get("/town/login").text
    assert '<label for="password"' in html
    assert 'type="password"' in html
    assert 'autocomplete="current-password"' in html


def test_wrong_password_401(town):
    resp = login(town, "nope")
    assert resp.status_code == 401
    assert "That password isn't right." in html.unescape(resp.text)
    assert town_auth.SESSION_COOKIE not in resp.headers.get("set-cookie", "")
    assert town.get("/town", follow_redirects=False).status_code == 303


def test_rate_limit_after_five_failures(town):
    for _ in range(5):
        assert login(town, "wrong").status_code == 401
    resp = login(town)  # even the right password is blocked now
    assert resp.status_code == 429
    assert "Too many sign-in attempts" in resp.text
    assert town_auth.SESSION_COOKIE not in resp.headers.get("set-cookie", "")


def test_successful_login_sets_secure_cookie(town):
    resp = login(town)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/town"
    cookie = resp.headers["set-cookie"]
    assert cookie.startswith(f"{town_auth.SESSION_COOKIE}=")
    lowered = cookie.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "path=/town" in lowered
    assert f"max-age={8 * 3600}" in lowered
    assert "secure" not in lowered  # plain http test server
    assert town.get("/town").status_code == 200


def test_cookie_secure_over_https(town):
    with TestClient(app, base_url="https://testserver") as c:
        cookie = login(c).headers["set-cookie"].lower()
    assert "secure" in cookie


def _get_with_cookie(c, token):
    c.cookies.clear()
    return c.get("/town", headers={"Cookie": f"{town_auth.SESSION_COOKIE}={token}"}, follow_redirects=False)


def test_tampered_and_expired_cookies_rejected(town):
    good = town_auth.issue_session(SECRET)
    assert _get_with_cookie(town, good).status_code == 200
    issued, nonce, sig = good.split(".")
    tampered = [
        f"{issued}.{nonce}.{sig[:-1]}{'0' if sig[-1] != '0' else '1'}",
        f"{int(issued) + 1}.{nonce}.{sig}",
        f"{issued}.{nonce}x.{sig}",
        town_auth.issue_session("y" * 40),  # signed with another secret
        "garbage",
        "",
    ]
    for token in tampered:
        assert _get_with_cookie(town, token).status_code == 303
    expired = town_auth.issue_session(SECRET, now=time.time() - town_auth.SESSION_MAX_AGE - 5)
    assert _get_with_cookie(town, expired).status_code == 303
    future = town_auth.issue_session(SECRET, now=time.time() + 3600)
    assert _get_with_cookie(town, future).status_code == 303


def test_logout_requires_csrf_and_clears_cookie(town):
    login(town)
    page = town.get("/town").text
    assert town.post("/town/logout", follow_redirects=False).status_code == 403
    assert town.post("/town/logout", data={"csrf_token": "bad"}, follow_redirects=False).status_code == 403
    resp = town.post("/town/logout", data={"csrf_token": csrf_from(page)}, follow_redirects=False)
    assert resp.status_code == 303
    cookie = resp.headers["set-cookie"].lower()
    assert town_auth.SESSION_COOKIE in cookie and "max-age=0" in cookie and "path=/town" in cookie
    assert town.get("/town", follow_redirects=False).status_code == 303


def test_csrf_token_tied_to_session(town, seeded):
    login(town)
    first = csrf_from(town.get("/town").text)
    town.cookies.clear()
    login(town)  # new session, new nonce
    resp = town.post("/town/building/status", data={"key": ELM_KEY, "status": "scheduled", "csrf_token": first},
                     follow_redirects=False)
    assert resp.status_code == 403
    assert get_status(seeded, ELM_KEY)["status"] == "open"


# --- Dashboard ----------------------------------------------------------------------------


def test_dashboard_ranking_statement_and_order(town, seeded, boston_db):
    login(town)
    html = town.get("/town").text
    assert RANKING_STATEMENT in html
    expected = [b.building_key for b in rank_real_buildings(seeded, boston_db)][:50]
    assert KEY_RE.findall(real_table(html)) == expected
    assert "<caption" in html and '<th scope="col"' in html and '<th scope="row"' in html
    assert 'aria-live="polite"' in html


def test_score_parts_shown(town, seeded, boston_db):
    login(town)
    table = real_table(town.get("/town").text)
    for b in rank_real_buildings(seeded, boston_db):
        row = table[table.index(f'data-building-key="{b.building_key}"'):]
        row = row[: row.index("</tr>")]
        for value in (b.tenant_score, b.official_score, b.total_score):
            assert f">{value:.1f}<" in row


def test_simulated_rows_badged_and_masked(town, seeded):
    login(town)
    html = town.get("/town").text
    section = sim_section(html)
    assert "simulated demo data, not real buildings" in section
    rows = re.findall(r'<tr class="sim-row">(.*?)</tr>', section, re.S)
    assert len(rows) == 8
    for row in rows:
        assert "SIMULATED" in row
        assert "Simulated report · Ward 21 · 3-family" in row
        assert "/town/building" not in row
    for leak in ("London", "Fake St", LONDON, OAK_DORCHESTER, "02128", "PARCEL"):
        assert leak not in section
    table = real_table(html)
    assert "SIM-" not in table and "Simulated" not in table and "SIMULATED" not in table


def test_simulated_detail_masked(town, seeded):
    login(town)
    resp = town.get("/town/simulated/SIM-03")
    assert resp.status_code == 200
    assert resp.text.count("SIMULATED") >= 1 + 5  # heading badge + one per report
    assert "not a real building" in resp.text
    assert "2026-10" in resp.text and "2026-10-01" not in resp.text and "2026-10-02" not in resp.text
    assert "Fictional smoke alarm story" in resp.text
    assert town.get("/town/simulated/SIM-99").status_code == 404
    assert town.get("/town/simulated/not-a-sim").status_code == 404


def test_filters_full_page_and_htmx(town, seeded, boston_db):
    login(town)
    html = town.get("/town?zip=02134").text
    assert KEY_RE.findall(real_table(html)) == [ELM_KEY]
    assert "Simulated tenant reports" in html  # full page
    partial = town.get("/town?zip=02134", headers={"HX-Request": "true", "HX-Target": "town-results"})
    assert "<html" not in partial.text and "Simulated tenant reports" not in partial.text
    assert KEY_RE.findall(partial.text) == [ELM_KEY]
    by_cat = town.get("/town?category=smoke_alarm").text
    expected = [b.building_key for b in rank_real_buildings(seeded, boston_db, category="smoke_alarm")]
    assert KEY_RE.findall(real_table(by_cat)) == expected
    assert APT_KEY in expected and ELM_KEY not in expected
    fire = town.get("/town?category=heating&zip=02134").text
    assert KEY_RE.findall(real_table(fire)) == [ELM_KEY]


def test_bad_filters_ignored(town, seeded, boston_db):
    login(town)
    html = town.get("/town?zip=abc&category=bogus").text
    assert "Enter a 5-digit ZIP code." in html
    assert len(KEY_RE.findall(real_table(html))) == len(rank_real_buildings(seeded, boston_db))


def test_limit_and_show_more(town, seeded, boston_db):
    login(town)
    html = town.get("/town?limit=2").text
    assert len(KEY_RE.findall(real_table(html))) == 2
    assert "Show more buildings" in html and "limit=52" in html


# --- Building detail ----------------------------------------------------------------------


def test_detail_month_dates_and_no_raw_address(town, seeded):
    login(town)
    url = f"/town/building?key={APT_KEY.replace(' ', '%20')}"
    html = main_of(town.get(url).text)
    assert "12 Fake St 02128" in html
    assert "Apt" not in html and not re.search(r"\b3R\b", html) and APT_ADDRESS not in html
    assert "2026-09" in html
    assert "2026-09-15" not in html and "2026-09-20" not in html
    assert "Missing or broken smoke or carbon monoxide alarm, Blocked exit or stairway" in html
    assert "Alarm in the hallway was removed." in html
    assert "contact" in html.lower() or "phone numbers removed" in html
    assert "Official records aren't shown" in html
    # Typed unit numbers never reach the dashboard either.
    dash = main_of(town.get("/town").text)
    assert not re.search(r"\b(3R|9Q)\b", dash) and "Unit" not in dash


def test_rental_detail_shows_official_history(town, seeded):
    login(town)
    html = town.get(f"/town/building?key=PARCEL%20{LONDON}").text
    assert "Boston building records" in html
    assert "182 London St" in html
    assert "#2" not in html  # typed unit not shown
    assert "Official records aren't shown" not in html


def test_non_rental_detail_hides_official_history(town, seeded):
    login(town)
    html = town.get(f"/town/building?key=PARCEL%20{OAK_DORCHESTER}").text
    assert "Official records aren't shown" in html
    assert "Boston building records" not in html
    assert OAK_DORCHESTER not in html.replace(f"PARCEL {OAK_DORCHESTER}", "")


def test_unknown_building_404(town, seeded):
    login(town)
    assert town.get("/town/building?key=NOPE%201%20ST").status_code == 404
    assert town.get("/town/building").status_code == 404


def test_status_update_htmx_and_fallback(town, seeded, boston_db):
    login(town)
    url = f"/town/building?key=PARCEL%20{LONDON}"
    token = csrf_from(town.get(url).text)
    before = rank_real_buildings(seeded, boston_db)
    resp = town.post(
        "/town/building/status",
        data={"key": f"PARCEL {LONDON}", "status": "inspected", "csrf_token": token},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "<html" not in resp.text and 'aria-live="polite"' in resp.text
    assert "Inspected" in resp.text and "Status saved." in resp.text
    assert get_status(seeded, f"PARCEL {LONDON}")["status"] == "inspected"
    assert rank_real_buildings(seeded, boston_db) == before  # status isn't a ranking input
    row = real_table(town.get("/town").text)
    row = row[row.index(f'data-building-key="PARCEL {LONDON}"'):]
    assert "status-inspected" in row[: row.index("</tr>")]
    # No-JS fallback: redirect back to the detail page.
    resp = town.post("/town/building/status",
                     data={"key": ELM_KEY, "status": "scheduled", "csrf_token": token}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/town/building?key=5%20ELM%20ST%2002134"
    assert "Inspection scheduled" in town.get(resp.headers["location"]).text


def test_status_update_rejections(town, seeded):
    login(town)
    token = csrf_from(town.get("/town").text)
    no_csrf = town.post("/town/building/status", data={"key": ELM_KEY, "status": "inspected"})
    assert no_csrf.status_code == 403
    header_ok = town.post("/town/building/status", data={"key": ELM_KEY, "status": "scheduled"},
                          headers={"X-CSRF-Token": token}, follow_redirects=False)
    assert header_ok.status_code == 303
    bad = town.post("/town/building/status", data={"key": ELM_KEY, "status": "closed", "csrf_token": token})
    assert bad.status_code == 422
    unknown = town.post("/town/building/status", data={"key": "NOPE", "status": "open", "csrf_token": token})
    assert unknown.status_code == 404
    with sqlite3.connect(seeded) as con:
        assert con.execute("SELECT building_key, status FROM building_status").fetchall() == [(ELM_KEY, "scheduled")]
    town.cookies.clear()
    anon = town.post("/town/building/status", data={"key": ELM_KEY, "status": "open", "csrf_token": token},
                     follow_redirects=False)
    assert anon.status_code == 303 and anon.headers["location"] == "/town/login"


def test_password_never_in_any_response(town, seeded):
    responses = [login(town, "wrong-guess"), town.get("/town/login"), login(town)]
    responses += [town.get(p) for p in (
        "/town", "/town?zip=02128", f"/town/building?key=PARCEL%20{LONDON}", "/town/simulated/SIM-01", "/health",
    )]
    for r in responses:
        assert PASSWORD not in r.text
        assert "wrong-guess" not in r.text
        assert SECRET not in r.text
        assert all(PASSWORD not in v and SECRET not in v for v in r.headers.values())
