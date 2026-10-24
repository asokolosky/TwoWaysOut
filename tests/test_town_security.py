"""Town dashboard security, privacy, and accessibility gaps not covered by tests/test_town.py.

Reuses test_town's fixtures (town, seeded, boston_db, town_limiter) and helpers.
"""
import html as html_lib
import re
import sqlite3
from html.parser import HTMLParser

import pytest
from starlette.routing import Route

from app.config import Settings, get_settings
from app.content.report_categories import REPORT_CATEGORIES
from app.main import TOO_LONG_MESSAGE, app
from app.routers.town import CATEGORY_OPTIONS, LOGIN_PATH, building_url
from app.services import town_auth
from app.services.building_status import get_status
from tests.test_town import (  # noqa: F401  (fixtures are used by name)
    APT_KEY,
    ELM_KEY,
    LONDON,
    PASSWORD,
    SECRET,
    add_report,
    boston_db,
    csrf_from,
    login,
    main_of,
    real_table,
    seeded,
    town,
    town_limiter,
)

DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
LONDON_KEY = f"PARCEL {LONDON}"
LONDON_URL = building_url(LONDON_KEY)


def configure(password=PASSWORD, secret=SECRET):
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, dashboard_password=password, session_secret=secret
    )


def session_cookie(c):
    value = c.cookies.get(town_auth.SESSION_COOKIE)
    assert value, "no session cookie after login"
    return value


def get_with_cookie(c, path, token):
    c.cookies.clear()
    return c.get(path, headers={"Cookie": f"{town_auth.SESSION_COOKIE}={token}"}, follow_redirects=False)


def status_rows(db):
    with sqlite3.connect(db) as con:
        return con.execute("SELECT building_key, status FROM building_status").fetchall()


def section(page, start_marker, end_marker):
    start = page.index(start_marker)
    return page[start : page.index(end_marker, start)]


# --- Sessions and cookies -----------------------------------------------------------------


def test_old_cookie_rejected_after_logout(town):
    login(town)
    old = session_cookie(town)
    token = csrf_from(town.get("/town").text)
    assert town.post("/town/logout", data={"csrf_token": token}, follow_redirects=False).status_code == 303
    assert get_with_cookie(town, "/town", old).status_code == 303


def test_cookie_scoped_to_town_path(town):
    login(town)
    assert town_auth.SESSION_COOKIE in town.cookies
    for path in ("/", "/health"):
        sent = town.get(path).request.headers.get("cookie", "")
        assert town_auth.SESSION_COOKIE not in sent
    sent = town.get("/town").request.headers.get("cookie", "")
    assert town_auth.SESSION_COOKIE in sent


def test_cookie_from_other_secret_rejected_after_rotation(town):
    login(town)
    old = session_cookie(town)
    assert get_with_cookie(town, "/town", old).status_code == 200
    configure(secret="z" * 40)  # SESSION_SECRET rotated
    assert get_with_cookie(town, "/town", old).status_code == 303
    assert get_with_cookie(town, LONDON_URL, old).status_code == 303


# --- CSRF ---------------------------------------------------------------------------------


def test_get_status_endpoint_does_not_change_status(town, seeded):
    login(town)
    resp = town.get(f"/town/building/status?key={ELM_KEY}&status=inspected", follow_redirects=False)
    assert resp.status_code == 405
    assert status_rows(seeded) == []
    assert get_status(seeded, ELM_KEY)["status"] == "open"


@pytest.mark.parametrize("variant", ["empty", "leading_space", "trailing_space", "both", "newline"])
def test_csrf_token_must_match_exactly(town, seeded, variant):
    login(town)
    token = csrf_from(town.get("/town").text)
    supplied = {
        "empty": "",
        "leading_space": f" {token}",
        "trailing_space": f"{token} ",
        "both": f"  {token}  ",
        "newline": f"{token}\n",
    }[variant]
    resp = town.post("/town/building/status", data={"key": ELM_KEY, "status": "inspected", "csrf_token": supplied},
                     follow_redirects=False)
    assert resp.status_code == 403
    assert status_rows(seeded) == []


def test_header_csrf_token_from_other_session_rejected(town, seeded):
    login(town)
    first = csrf_from(town.get("/town").text)
    town.cookies.clear()
    login(town)
    resp = town.post("/town/building/status", data={"key": ELM_KEY, "status": "scheduled"},
                     headers={"X-CSRF-Token": first}, follow_redirects=False)
    assert resp.status_code == 403
    assert status_rows(seeded) == []
    # Logout with another session's header token is refused too.
    resp = town.post("/town/logout", headers={"X-CSRF-Token": first}, follow_redirects=False)
    assert resp.status_code == 403


# --- Status input -------------------------------------------------------------------------


def test_status_overlong_key_friendly_422(town, seeded):
    login(town)
    token = csrf_from(town.get("/town").text)
    long_key = "LONGKEYMARKER" + "A" * 300
    resp = town.post("/town/building/status", data={"key": long_key, "status": "open", "csrf_token": token})
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("text/html")
    assert TOO_LONG_MESSAGE in html_lib.unescape(resp.text)
    assert "LONGKEYMARKER" not in resp.text
    assert '"detail"' not in resp.text
    assert status_rows(seeded) == []
    detail = town.get("/town/building?key=" + "LONGKEYMARKER" + "B" * 300)
    assert detail.status_code == 422
    assert "LONGKEYMARKER" not in detail.text


def test_simulated_id_is_not_a_real_building(town, seeded):
    login(town)
    token = csrf_from(town.get("/town").text)
    resp = town.post("/town/building/status", data={"key": "SIM-01", "status": "inspected", "csrf_token": token})
    assert resp.status_code == 404
    assert town.get("/town/building?key=SIM-01").status_code == 404
    assert status_rows(seeded) == []


@pytest.mark.parametrize("value", ["Inspected", "INSPECTED", "Open", " inspected", "inspected ", "scheduled\n"])
def test_status_values_are_case_and_space_sensitive(town, seeded, value):
    login(town)
    token = csrf_from(town.get("/town").text)
    resp = town.post("/town/building/status", data={"key": ELM_KEY, "status": value, "csrf_token": token})
    assert resp.status_code == 422
    assert status_rows(seeded) == []


# --- Login --------------------------------------------------------------------------------


def test_unicode_password(town):
    unicode_pw = "pässwörd-火災-🔥"
    configure(password=unicode_pw)
    assert login(town, "passwurd-火災-🔥").status_code == 401
    assert login(town, "pässwörd").status_code == 401
    resp = login(town, unicode_pw)
    assert resp.status_code == 303
    assert town.get("/town").status_code == 200


def test_password_whitespace_not_trimmed(town):
    """Documented behavior: the submitted password is compared byte for byte, no trimming."""
    assert login(town, f" {PASSWORD}").status_code == 401
    assert login(town, f"{PASSWORD} ").status_code == 401
    assert login(town, f"{PASSWORD}\n").status_code == 401
    configure(password=" padded ")
    assert login(town, "padded").status_code == 401
    assert login(town, " padded ").status_code == 303


def test_failed_password_never_reflected_in_value(town):
    attempt = "Wr0ngGuessMarker"
    resp = login(town, attempt)
    assert resp.status_code == 401
    assert attempt not in resp.text
    for tag in re.findall(r"<input[^>]*>", resp.text):
        if 'type="password"' in tag:
            assert "value=" not in tag


def test_successful_logins_do_not_consume_rate_limit(town):
    for _ in range(6):
        assert login(town).status_code == 303
        town.cookies.clear()
    assert login(town, "wrong").status_code == 401


# --- Every protected route requires a session ---------------------------------------------


def _all_routes():
    """Flat (path, methods) routes. FastAPI 0.16x wraps included routers in _IncludedRouter,
    whose routes are exposed through effective_route_contexts; older versions list them directly."""
    for route in app.routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is not None:
            yield from (contexts() if callable(contexts) else contexts)
        elif isinstance(route, Route):
            yield route


def _town_routes():
    out = []
    for route in _all_routes():
        if not route.path.startswith("/town"):
            continue
        if route.path == LOGIN_PATH:
            continue
        path = re.sub(r"\{[^}]+\}", "SIM-00", route.path)
        for method in sorted(route.methods - {"HEAD"}):
            out.append((method, path))
    return out


TOWN_ROUTES = _town_routes()


def test_route_enumeration_found_town_routes():
    paths = {p for _, p in TOWN_ROUTES}
    assert {"/town", "/town/building", "/town/building/status", "/town/logout", "/town/simulated/SIM-00"} <= paths


@pytest.mark.parametrize(("method", "path"), TOWN_ROUTES)
def test_every_town_route_redirects_when_signed_out(town, seeded, method, path):
    resp = town.request(method, path, follow_redirects=False)
    assert resp.status_code == 303, (method, path)
    assert resp.headers["location"] == LOGIN_PATH
    assert town_auth.SESSION_COOKIE not in resp.headers.get("set-cookie", "")
    assert status_rows(seeded) == []


# --- XSS ----------------------------------------------------------------------------------


def test_report_html_is_escaped(town, app_db):
    key = "<b>x</b> 1 ST 02134"
    add_report(app_db, key=key, address="<b>x</b> 1 St 02134", category="smoke_alarm", zip_code="02134",
               description="<script>alert(1)</script>")
    login(town)
    for page in (town.get("/town").text, town.get("/town?zip=02134").text):
        body = main_of(page)
        assert "<b>x</b>" not in body.lower()
        assert "<script>alert(1)</script>" not in body
        assert "&lt;b&gt;" in body.lower()
    resp = town.get(building_url(key))
    assert resp.status_code == 200
    body = main_of(resp.text)
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "<b>x</b>" not in body.lower()
    assert "&lt;b&gt;" in body.lower()
    # The <title> is outside <main>; check it too.
    assert "<b>" not in resp.text[: resp.text.index("<main")].lower()


# --- Privacy ------------------------------------------------------------------------------


def test_no_full_tenant_dates_on_dashboard_or_detail(town, seeded):
    login(town)
    assert not DATE_RE.search(real_table(town.get("/town").text))
    for key in (APT_KEY, ELM_KEY, LONDON_KEY):
        page = town.get(building_url(key)).text
        tenant = section(page, 'id="reports-heading"', 'id="official-heading"')
        assert not DATE_RE.search(tenant), key


SIM_MARKERS = ("SIM-", "Simulated", "SIMULATED", "Fictional smoke alarm story", "Ward 21")


@pytest.mark.parametrize("zip_code", ["", "02134", "02128", "02122"])
def test_simulated_never_in_real_results_under_any_filter(town, seeded, zip_code):
    login(town)
    for category in [""] + [cid for cid, _ in CATEGORY_OPTIONS]:
        resp = town.get(
            f"/town?zip={zip_code}&category={category}",
            headers={"HX-Request": "true", "HX-Target": "town-results"},
        )
        assert resp.status_code == 200
        for marker in SIM_MARKERS:
            assert marker not in resp.text, (zip_code, category, marker)
    # Every simulated report category is a filter option, so the loop above covered them all.
    assert set(REPORT_CATEGORIES) <= {cid for cid, _ in CATEGORY_OPTIONS}


# --- Response headers ---------------------------------------------------------------------


def _authed_pages(town):
    login(town)
    return [town.get("/town"), town.get(LONDON_URL)]


def test_authenticated_pages_not_cached(town, seeded):
    for resp in _authed_pages(town):
        assert "no-store" in resp.headers.get("cache-control", "").lower()


def test_authenticated_pages_send_referrer_policy(town, seeded):
    for resp in _authed_pages(town):
        assert resp.headers.get("referrer-policy", "").lower() in {"no-referrer", "same-origin", "strict-origin"}


# --- Accessibility ------------------------------------------------------------------------


class _A11yParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.label_for: set[str] = set()
        self.controls: list[dict] = []
        self.tables = 0
        self.captions = 0
        self.ths: list[dict] = []
        self.live: list[dict] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "label" and a.get("for"):
            self.label_for.add(a["for"])
        elif tag in ("input", "select", "textarea"):
            self.controls.append({"tag": tag, **a})
        elif tag == "table":
            self.tables += 1
        elif tag == "caption":
            self.captions += 1
        elif tag == "th":
            self.ths.append(a)
        if a.get("aria-live"):
            self.live.append(a)


def _parse(page):
    p = _A11yParser()
    p.feed(main_of(page))
    return p


HONEYPOT_NAMES = {"website", "url", "homepage"}


def _assert_controls_labeled(p):
    for c in p.controls:
        if c.get("type") == "hidden" or c.get("name") in HONEYPOT_NAMES:
            continue
        labeled = (c.get("id") and c["id"] in p.label_for) or c.get("aria-label") or c.get("aria-labelledby")
        assert labeled, f"unlabeled control: {c}"


def test_dashboard_accessibility(town, seeded):
    login(town)
    p = _parse(town.get("/town").text)
    assert p.controls, "dashboard has no filter controls"
    _assert_controls_labeled(p)
    assert p.tables == 2 and p.captions == p.tables
    assert p.ths and all(th.get("scope") in ("col", "row") for th in p.ths)
    assert any(lr.get("id") == "town-results" and lr["aria-live"] == "polite" for lr in p.live)


def test_building_detail_accessibility(town, seeded):
    login(town)
    for key in (LONDON_KEY, APT_KEY):
        p = _parse(town.get(building_url(key)).text)
        assert any(c["tag"] == "select" for c in p.controls)
        _assert_controls_labeled(p)
        assert p.captions >= p.tables
        assert all(th.get("scope") in ("col", "row") for th in p.ths)
        assert any(lr.get("id") == "building-status" and lr["aria-live"] == "polite" for lr in p.live)
