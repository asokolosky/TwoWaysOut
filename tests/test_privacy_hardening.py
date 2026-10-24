"""Logging, request-size, and validation-error privacy guards in app/main.py."""

import logging

from app.main import MAX_REQUEST_BYTES, TOO_LONG_MESSAGE

FORM = {"content-type": "application/x-www-form-urlencoded"}


def test_uvicorn_access_log_disabled():
    import app.main  # noqa: F401

    log = logging.getLogger("uvicorn.access")
    assert log.disabled
    assert not log.propagate
    # (pytest's log capture may attach its own handlers, so handlers aren't checked here.)


def test_sdk_loggers_capped_at_warning():
    import app.main  # noqa: F401

    for name in ("anthropic", "httpx", "httpx2", "httpcore"):
        assert logging.getLogger(name).level == logging.WARNING


# --- Request size guard -------------------------------------------------------------------

def _chunks(total: int, size: int = 64 * 1024):
    yield b"listing="
    sent = 0
    while sent < total:
        n = min(size, total - sent)
        yield b"x" * n
        sent += n


def test_chunked_request_over_limit_rejected(client):
    resp = client.post("/check", content=_chunks(MAX_REQUEST_BYTES + 10), headers=FORM)
    assert resp.status_code == 413
    assert "too large" in resp.text


def test_small_chunked_request_succeeds(client):
    def body():
        yield b"listing=2BR+apartment.+"
        yield b"No+smoke+detectors+in+the+bedroom."

    resp = client.post("/check", content=body(), headers={**FORM, "HX-Request": "true"})
    assert resp.status_code == 200
    assert "Fire-safety report" in resp.text


def test_content_length_over_limit_rejected(client):
    resp = client.post("/check", content=b"listing=" + b"x" * (MAX_REQUEST_BYTES + 1), headers=FORM)
    assert resp.status_code == 413


def test_normal_requests_unaffected(client):
    assert client.get("/check").status_code == 200
    assert client.get("/").status_code == 200


# --- Validation errors never echo input ---------------------------------------------------

def test_report_over_hard_cap_gets_friendly_page(client):
    marker = "ECHOCHECK"
    resp = client.post("/report", data={"address": marker * 300, "category": "other"})
    assert resp.status_code == 422
    assert TOO_LONG_MESSAGE in resp.text
    assert "Report a fire-safety problem" in resp.text
    assert marker not in resp.text


def test_report_over_hard_cap_htmx(client):
    resp = client.post(
        "/report", data={"description": "z" * 20_000}, headers={"HX-Request": "true"}
    )
    assert resp.status_code == 200
    assert TOO_LONG_MESSAGE in resp.text and "zzzz" not in resp.text
