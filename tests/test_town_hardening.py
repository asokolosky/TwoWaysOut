"""Task 9 review fixes: security headers, server-side logout, Secure cookie setting,
non-ASCII tokens, password digest compare, and the login limiter reservation."""
import sqlite3
import time

from app.config import Settings, get_settings
from app.main import app
from app.services import town_auth
from app.services.rate_limit import RateLimiter
from tests.test_town import (  # noqa: F401  (fixtures are used by name)
    PASSWORD,
    SECRET,
    boston_db,
    csrf_from,
    login,
    seeded,
    town,
    town_limiter,
)


def revoked_rows(db):
    with sqlite3.connect(db) as con:
        return con.execute("SELECT nonce, expires_at FROM revoked_sessions").fetchall()


def logout(c):
    token = csrf_from(c.get("/town").text)
    return c.post("/town/logout", data={"csrf_token": token}, follow_redirects=False)


# --- Headers ------------------------------------------------------------------------------


def test_logout_sends_clear_site_data(town):
    login(town)
    resp = logout(town)
    assert resp.status_code == 303
    assert resp.headers["clear-site-data"] == '"cache", "storage"'


def test_failed_logout_does_not_send_clear_site_data(town):
    login(town)
    resp = town.post("/town/logout", data={"csrf_token": "nope"}, follow_redirects=False)
    assert resp.status_code == 403
    assert "clear-site-data" not in resp.headers


def test_public_page_security_headers(client):
    resp = client.get("/")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "no-store" not in resp.headers.get("cache-control", "")


def test_town_login_page_not_cached(town):
    resp = town.get("/town/login")
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["pragma"] == "no-cache"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["x-frame-options"] == "DENY"


def test_redirects_from_town_not_cached(town):
    resp = town.get("/town", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["cache-control"] == "no-store"


# --- Server-side logout -------------------------------------------------------------------


def test_logout_records_revoked_session(town, app_db):
    login(town)
    token = town.cookies.get(town_auth.SESSION_COOKIE)
    nonce, issued = town_auth.session_info(SECRET, token)
    assert revoked_rows(app_db) == []
    assert logout(town).status_code == 303
    assert revoked_rows(app_db) == [(nonce, issued + town_auth.SESSION_MAX_AGE)]


def test_logout_prunes_expired_revocations(town, app_db):
    now = int(time.time())
    with sqlite3.connect(app_db) as con:
        con.execute("INSERT INTO revoked_sessions VALUES ('old-nonce', ?)", (now - 10,))
        con.execute("INSERT INTO revoked_sessions VALUES ('live-nonce', ?)", (now + 3600,))
    login(town)
    assert logout(town).status_code == 303
    nonces = {n for n, _ in revoked_rows(app_db)}
    assert "old-nonce" not in nonces
    assert "live-nonce" in nonces
    assert len(nonces) == 2


def test_revoked_cookie_cannot_reach_login_redirect_loop(town):
    login(town)
    old = town.cookies.get(town_auth.SESSION_COOKIE)
    assert logout(town).status_code == 303
    town.cookies.clear()
    resp = town.get("/town/login", headers={"Cookie": f"{town_auth.SESSION_COOKIE}={old}"},
                    follow_redirects=False)
    assert resp.status_code == 200  # shows the form instead of bouncing to /town


def test_other_sessions_survive_one_logout(town):
    login(town)
    first = town.cookies.get(town_auth.SESSION_COOKIE)
    town.cookies.clear()
    login(town)
    assert logout(town).status_code == 303
    town.cookies.clear()
    resp = town.get("/town", headers={"Cookie": f"{town_auth.SESSION_COOKIE}={first}"}, follow_redirects=False)
    assert resp.status_code == 200


# --- Secure cookie setting ----------------------------------------------------------------


def test_force_secure_cookies_setting(town):
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, dashboard_password=PASSWORD, session_secret=SECRET, force_secure_cookies=True
    )
    resp = login(town)  # plain http test server
    assert resp.status_code == 303
    assert "secure" in resp.headers["set-cookie"].lower()


def test_force_secure_cookies_defaults_off():
    assert Settings(_env_file=None).force_secure_cookies is False


# --- Non-ASCII tokens ---------------------------------------------------------------------


def test_non_ascii_cookie_redirects_not_500(town):
    login(town)
    good = town.cookies.get(town_auth.SESSION_COOKIE)
    town.cookies.clear()
    bad = good[:-1] + "é"
    resp = town.get("/town", headers={"Cookie": f"{town_auth.SESSION_COOKIE}={bad}".encode()},
                    follow_redirects=False)
    assert resp.status_code == 303


def test_non_ascii_csrf_token_forbidden_not_500(town, seeded):
    login(town)
    token = csrf_from(town.get("/town").text)
    resp = town.post("/town/logout", data={"csrf_token": token[:-1] + "é"}, follow_redirects=False)
    assert resp.status_code == 403
    resp = town.post("/town/building/status", data={"key": "x", "status": "open"},
                     headers={"X-CSRF-Token": (token[:-1] + "é").encode()}, follow_redirects=False)
    assert resp.status_code == 403


def test_verify_session_rejects_non_ascii_unit():
    token = town_auth.issue_session(SECRET)
    assert town_auth.verify_session(SECRET, token) is not None
    assert town_auth.verify_session(SECRET, token[:-1] + "é") is None
    issued, nonce, sig = token.split(".")
    assert town_auth.verify_session(SECRET, f"²{issued}.{nonce}.{sig}") is None
    assert town_auth.check_csrf(SECRET, nonce, "é" * 64) is False


# --- Password compare ---------------------------------------------------------------------


def test_check_password_digest_compare():
    s = Settings(_env_file=None, dashboard_password="secret-pass")
    assert town_auth.check_password(s, "secret-pass")
    assert not town_auth.check_password(s, "secret-pass" * 50)
    assert not town_auth.check_password(s, "")
    empty = Settings(_env_file=None, dashboard_password="")
    assert not town_auth.check_password(empty, "")


# --- Login limiter ------------------------------------------------------------------------


def test_rate_limiter_refund():
    now = [0.0]
    rl = RateLimiter(limit=2, window_seconds=60, clock=lambda: now[0])
    assert rl.allow("a") and rl.allow("a") and not rl.allow("a")
    rl.refund("a")
    assert rl.allow("a")
    rl.refund("never-seen")  # no error


def test_login_reserves_attempt_before_checking(town, town_limiter):
    for _ in range(5):
        assert login(town, "wrong").status_code == 401
    assert town_limiter.is_limited("testclient")
    # At the limit even the right password is refused, and the refused try isn't counted.
    assert login(town).status_code == 429
