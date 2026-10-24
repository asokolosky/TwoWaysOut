"""Round 2: Content-Security-Policy on every public page (including POST /check results and
errors), and no inline scripts or on*= handlers in templates or in rendered HTML."""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from app.main import CONTENT_SECURITY_POLICY, app
from app.services.boston import get_boston_db
from tests.fixtures.boston_db import build_fixture_db
from tests.fixtures.listings import RECIPE, SPARSE

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"
HX = {"HX-Request": "true"}
ADDRESSES = ["182 London St, East Boston 02128", "12 Example St, Amherst, MA 01002", ""]


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    return build_fixture_db(tmp_path_factory.mktemp("round2_csp") / "boston.sqlite")


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inline_scripts = 0
        self.handlers: list[tuple[str, str]] = []
        self._in_script = False
        self._script_has_src = False

    def handle_starttag(self, tag, attrs):
        for name, _ in attrs:
            if name.lower().startswith("on") or name.lower().startswith("hx-on"):
                self.handlers.append((tag, name))
        if tag == "script":
            self._in_script = True
            self._script_has_src = any(n == "src" for n, _ in attrs)

    def handle_data(self, data):
        if self._in_script and not self._script_has_src and data.strip():
            self.inline_scripts += 1

    def handle_endtag(self, tag):
        if tag == "script":
            if self._in_script and not self._script_has_src:
                self.inline_scripts += 1  # an empty inline <script></script> still counts
            self._in_script = False


def _assert_no_inline_js(page: str, where: str):
    p = _Scripts()
    p.feed(page)
    assert p.inline_scripts == 0, f"inline <script> in {where}"
    assert p.handlers == [], f"inline handlers in {where}: {p.handlers}"
    assert "javascript:" not in page.lower(), where


@pytest.mark.parametrize("path", ["/", "/check", "/about", "/report", "/town/login"])
def test_csp_on_get_pages(client, path):
    resp = client.get(path)
    # /town/login is 503 ("not configured") when no town password is set, as in tests.
    assert resp.status_code == (503 if path == "/town/login" else 200)
    assert resp.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    _assert_no_inline_js(resp.text, path)


@pytest.mark.parametrize("htmx", [True, False], ids=["htmx", "full_page"])
@pytest.mark.parametrize("address", ADDRESSES)
def test_csp_on_check_results(client, db, htmx, address):
    app.dependency_overrides[get_boston_db] = lambda: db
    resp = client.post("/check", data={"listing": SPARSE, "address": address}, headers=HX if htmx else {})
    assert resp.status_code == 200
    assert resp.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    _assert_no_inline_js(resp.text, f"POST /check {address!r}")


@pytest.mark.parametrize("htmx, status", [(True, 200), (False, 422)], ids=["htmx", "full_page"])
@pytest.mark.parametrize("listing", ["", RECIPE])
def test_csp_on_check_errors(client, htmx, status, listing):
    resp = client.post("/check", data={"listing": listing}, headers=HX if htmx else {})
    assert resp.status_code == status
    assert resp.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    _assert_no_inline_js(resp.text, "POST /check error")


def test_csp_on_404(client):
    resp = client.get("/no-such-page")
    assert resp.status_code == 404
    assert resp.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


@pytest.mark.parametrize("path", sorted(TEMPLATES.rglob("*.html")), ids=lambda p: p.name)
def test_template_has_no_inline_script_or_handlers(path):
    # Jinja comments and expressions are stripped first so they can't hide or fake a match.
    text = re.sub(r"\{#.*?#\}", "", path.read_text(), flags=re.S)
    for m in re.finditer(r"<script\b([^>]*)>", text, re.I):
        assert re.search(r"\bsrc\s*=", m.group(1)), f"inline <script> in {path.name}"
    for m in re.finditer(r"<[a-zA-Z][^>]*>", text):
        assert not re.search(r"\s(on[a-z]+|hx-on[:\w-]*)\s*=", m.group(0), re.I), (path.name, m.group(0))
