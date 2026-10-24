"""UI regression checks: loading indicator accessibility, pinned CDN scripts, reduced motion,
and the Content-Security-Policy header."""
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from app.main import CDN_SCRIPTS, CONTENT_SECURITY_POLICY, app

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
TEMPLATES = ROOT / "app" / "templates"
CSS = (STATIC / "styles.css").read_text()


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict]] = []
        self.stack: list[tuple[str, dict]] = []
        self.parents: dict[str, list[tuple[str, dict]]] = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if a.get("id"):
            self.parents[a["id"]] = list(self.stack)
        if tag not in ("input", "meta", "link", "br", "img", "path", "stop"):
            self.stack.append((tag, a))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def _parse(html: str) -> _Tags:
    p = _Tags()
    p.feed(html)
    return p


# --- Loading indicator (ui-and-about 12) ---------------------------------------------------


def _rule(selector_re: str) -> str:
    m = re.search(selector_re + r"\s*\{([^}]*)\}", CSS)
    assert m, selector_re
    return m.group(1)


def test_idle_indicator_is_hidden_from_assistive_technology():
    idle = _rule(r"\n\.htmx-indicator")
    assert "visibility: hidden" in idle  # opacity alone stays in the accessibility tree
    active = _rule(r"\.htmx-request \.htmx-indicator, \.htmx-request\.htmx-indicator")
    assert "visibility: visible" in active


def test_loading_text_sits_in_a_status_region(client):
    page = _parse(client.get("/check").text)
    indicator = next(a for t, a in page.tags if a.get("id") == "analyzing")
    assert "htmx-indicator" in indicator["class"].split()
    assert indicator.get("aria-hidden") is None
    assert any(a.get("role") == "status" for _, a in page.parents["analyzing"])
    form = next(a for t, a in page.tags if t == "form" and a.get("hx-post") == "/check")
    assert form["hx-indicator"] == "#analyzing"


# --- Pinned CDN scripts (ui-and-about 13.1) ------------------------------------------------

PINNED = {
    "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@": r"4\.\d+\.\d+",
    "https://cdn.jsdelivr.net/npm/htmx.org@": r"2\.\d+\.\d+",
}


@pytest.mark.parametrize("path", ["/", "/check", "/report", "/about", "/town"])
def test_cdn_scripts_are_pinned_with_sri(client, path):
    page = _parse(client.get(path).text)
    scripts = [a for t, a in page.tags if t == "script"]
    external = [a for a in scripts if a.get("src", "").startswith("https://")]
    assert len(external) == 2, external
    # Everything else is served from this site.
    local = [a.get("src", "") for a in scripts if a not in external]
    assert all(re.match(r"(http://testserver)?/static/", s) for s in local), local
    for a in external:
        prefix = next((p for p in PINNED if a["src"].startswith(p)), None)
        assert prefix, f"unexpected CDN script {a['src']}"
        version = a["src"][len(prefix):].split("/", 1)[0]
        assert re.fullmatch(PINNED[prefix], version), f"not an exact version: {a['src']}"
        assert re.fullmatch(r"sha384-[A-Za-z0-9+/]{64}", a.get("integrity", "")), a["src"]
        assert a.get("crossorigin") == "anonymous", a["src"]


# --- Reduced motion (ui-and-about 13.2) ----------------------------------------------------


def _reduced_motion_block() -> str:
    start = CSS.index("@media (prefers-reduced-motion: reduce)")
    depth, i = 0, CSS.index("{", start)
    for j in range(i, len(CSS)):
        depth += {"{": 1, "}": -1}.get(CSS[j], 0)
        if depth == 0:
            return CSS[i: j + 1]
    raise AssertionError("unclosed reduced-motion block")


def test_reduced_motion_block_covers_every_animation():
    block = _reduced_motion_block()
    # Floor plan is static and fully lit.
    assert re.search(r"\.floorplan\.is-animated \.fp-path[^{]*\{[^}]*animation: none", block)
    assert "stroke-dashoffset: 0" in block
    # Embers canvas is hidden.
    assert re.search(r"\.embers\s*\{\s*display: none", block)
    # Smoke has no drift, blur, or reveal.
    assert re.search(r"\.smoke::before, \.smoke::after\s*\{\s*animation: none", block)
    assert "filter: none" in block
    assert re.search(r"#report\.smoke-reveal\s*\{\s*animation: none", block)
    # Catch-all.
    catch_all = re.search(r"\*, \*::before, \*::after\s*\{([^}]*)\}", block)
    assert catch_all
    assert "animation: none !important" in catch_all.group(1)
    assert "transition: none !important" in catch_all.group(1)


def test_embers_script_respects_reduced_motion():
    js = (STATIC / "embers.js").read_text()
    assert 'matchMedia("(prefers-reduced-motion: reduce)")' in js
    assert "addEventListener" in js or "addListener" in js


# --- Content-Security-Policy (ui-and-about 15) ---------------------------------------------


def _csp(header: str) -> dict[str, list[str]]:
    out = {}
    for part in header.split(";"):
        name, *values = part.split()
        out[name] = values
    return out


@pytest.mark.parametrize("path", ["/", "/check", "/report", "/about", "/town", "/health", "/static/styles.css"])
def test_csp_header_on_every_response(client, path):
    resp = client.get(path)
    assert resp.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


def test_csp_directives():
    csp = _csp(CONTENT_SECURITY_POLICY)
    assert csp["default-src"] == ["'self'"]
    # Exact file paths only, and they must match the script tags actually rendered.
    assert csp["script-src"][0] == "'self'"
    assert set(csp["script-src"][1:]) == set(CDN_SCRIPTS)
    html = TestClient(app).get("/").text
    rendered = set(re.findall(r'<script src="(https://[^"]+)"', html))
    assert rendered == set(CDN_SCRIPTS)
    assert "'unsafe-inline'" not in csp["script-src"] and "'unsafe-eval'" not in csp["script-src"]
    # The Tailwind browser build and htmx inject <style> at runtime.
    assert csp["style-src"] == ["'self'", "'unsafe-inline'"]
    assert csp["img-src"] == ["'self'", "data:"]
    assert csp["object-src"] == ["'none'"]
    assert csp["base-uri"] == ["'self'"]
    assert csp["form-action"] == ["'self'"]
    assert csp["frame-ancestors"] == ["'none'"]


def test_csp_on_town_pages(client):
    assert client.get("/town/login").headers["content-security-policy"] == CONTENT_SECURITY_POLICY


INLINE_HANDLER_RE = re.compile(r"\son[a-z]+\s*=", re.I)


def test_templates_have_no_inline_scripts_or_handlers():
    """The CSP allows no inline scripts, so templates must not rely on them."""
    for f in sorted(TEMPLATES.rglob("*.html")):
        text = f.read_text()
        for m in re.finditer(r"<script\b([^>]*)>", text):
            assert "src=" in m.group(1), f"inline <script> in {f.name}"
        assert not INLINE_HANDLER_RE.search(text), f"inline event handler in {f.name}"
        assert "hx-on" not in text, f"hx-on (eval'd by htmx) in {f.name}"
        assert "javascript:" not in text, f"javascript: URL in {f.name}"
        assert "js:" not in re.sub(r"\.js\b", "", text), f"htmx js: expression in {f.name}"


def test_unused_coming_soon_template_is_gone():
    assert not (TEMPLATES / "coming_soon.html").exists()


def test_owned_static_urls_are_relative(client):
    """Behind a proxy uvicorn doesn't trust, absolute URLs would be http:// on an https page."""
    for path in ("/", "/check"):
        page = _parse(client.get(path).text)
        css = [a["href"] for t, a in page.tags if t == "link" and a.get("rel") == "stylesheet"]
        assert css == ["/static/styles.css"], path
    check = _parse(client.get("/check").text)
    assert {"src": "/static/smoke.js", "defer": None} in [a for t, a in check.tags if t == "script"]
