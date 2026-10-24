"""Final pass (Task 10): headers, UI text style, exact strings, About links, doc hygiene,
and an off-topic/privacy regression."""

import html
import re
import sqlite3
from html.parser import HTMLParser
from pathlib import Path

import pytest

from app.config import Settings, get_settings
from app.content.background import BACKGROUND
from app.content.copy import DISCLAIMER, RANKING_STATEMENT
from app.main import app
from app.routers.town import get_login_limiter
from app.services.ai_client import get_ai_client
from app.services.boston import get_boston_db
from app.services.rate_limit import RateLimiter
from app.services.relevance import NOT_A_LISTING_MESSAGE
from tests.fakes import FakeClient
from tests.fixtures import listings
from tests.fixtures.boston_db import build_fixture_db

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = "test-pass"
SECRET = "x" * 40
ADDRESS = "182 London St, East Boston 02128"
LONDON_KEY = "PARCEL 0106069000"
HX = {"HX-Request": "true"}


@pytest.fixture(scope="module")
def boston_db(tmp_path_factory):
    return build_fixture_db(tmp_path_factory.mktemp("boston") / "boston.sqlite")


@pytest.fixture
def town(client, boston_db):
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, dashboard_password=PASSWORD, session_secret=SECRET
    )
    app.dependency_overrides[get_boston_db] = lambda: boston_db
    app.dependency_overrides[get_login_limiter] = lambda: RateLimiter(limit=5, window_seconds=900)
    return client


@pytest.fixture
def signed_in(town):
    # A real report so the dashboard and building detail have a row.
    resp = town.post("/report", data={"address": ADDRESS, "category": ["blocked_exit"]})
    assert resp.status_code == 200
    assert town.post("/town/login", data={"password": PASSWORD}, follow_redirects=False).status_code == 303
    return town


BUILDING_URL = f"/town/building?key={LONDON_KEY.replace(' ', '%20')}"


# --- 1. Security headers ----------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/check", "/report", "/about"])
def test_public_page_security_headers(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_town_pages_security_headers(signed_in):
    for path in ("/town/login", "/town", BUILDING_URL):
        resp = signed_in.get(path)
        assert resp.status_code == 200, path
        assert resp.headers["cache-control"] == "no-store", path
        assert resp.headers["referrer-policy"] == "no-referrer", path
        assert resp.headers["x-content-type-options"] == "nosniff", path
        assert resp.headers["x-frame-options"] == "DENY", path


# --- 2. No em dashes or exclamation points in visible text -------------------------------------


class _VisibleText(HTMLParser):
    """Collects text nodes outside <script>, <style>, and <template>. Comments and doctype are skipped."""

    def __init__(self, skip_textarea: bool = False):
        self.SKIP = {"script", "style", "template"} | ({"textarea"} if skip_textarea else set())
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.chunks.append(data)


def _visible_text(page: str, skip_textarea: bool = False) -> str:
    p = _VisibleText(skip_textarea)
    p.feed(page)
    return " ".join(" ".join(p.chunks).split())


def _style_hits(text: str) -> list[str]:
    hits = []
    for m in re.finditer(r"[\u2014!]", text):
        hits.append(text[max(0, m.start() - 40): m.end() + 40])
    return hits


def _rendered_pages(town, app_db, boston_db) -> dict[str, str]:
    pages = {}
    for path in ("/", "/check", "/check?sample=1", "/report", "/about", "/town/login"):
        resp = town.get(path)
        assert resp.status_code == 200, path
        pages[path] = resp.text
    report = town.post("/check", data={"listing": listings.SPARSE}, headers=HX)
    assert report.status_code == 200
    pages["POST /check (HTMX, SPARSE)"] = report.text
    thanks = town.post("/report", data={"address": ADDRESS, "category": ["blocked_exit"]})
    assert thanks.status_code == 200
    pages["POST /report (confirmation)"] = thanks.text
    assert town.post("/town/login", data={"password": PASSWORD}, follow_redirects=False).status_code == 303
    dash = town.get("/town")
    assert dash.status_code == 200
    pages["/town (signed in)"] = dash.text
    building = town.get(BUILDING_URL)
    assert building.status_code == 200
    pages["/town/building (signed in)"] = building.text
    # Simulated detail with the real seeder's fictional descriptions.
    from scripts.seed_reports import seed

    sim_id = sorted(seed(app_db, boston_db)["buildings"])[0]
    sim = town.get(f"/town/simulated/{sim_id}")
    assert sim.status_code == 200
    pages["/town/simulated (signed in)"] = sim.text
    return pages


def test_visible_text_has_no_em_dash_or_exclamation(town, app_db, boston_db):
    # UI copy only; prefilled <textarea> content is checked separately below.
    findings = {}
    pages = _rendered_pages(town, app_db, boston_db)
    assert {"/town/building (signed in)", "/town/simulated (signed in)"} <= set(pages)
    for name, page in pages.items():
        hits = _style_hits(_visible_text(page, skip_textarea=True))
        if hits:
            findings[name] = hits
    assert not findings, f"em dash or '!' in visible UI text: {findings}"


def test_prefilled_sample_listing_has_no_em_dash_or_exclamation(client):
    # /check?sample=1 shows the sample listing in the textarea, so it's visible on the page.
    page = client.get("/check?sample=1").text
    hits = _style_hits(_visible_text(page))
    assert not hits, f"em dash or '!' in the prefilled sample listing: {hits}"


def test_visible_text_helper_ignores_scripts_and_comments():
    page = "<!DOCTYPE html><p>Plain text.</p><script>if (!x) {}</script><!-- hi! --><style>a{}</style>"
    assert _visible_text(page) == "Plain text."
    assert _style_hits(_visible_text("<p>Wow!</p>"))


# --- 3. Exact required strings ----------------------------------------------------------------


def test_disclaimer_on_every_student_report_and_confirmation(town):
    reports = {
        "HTMX SPARSE": town.post("/check", data={"listing": listings.SPARSE}, headers=HX),
        "HTMX DETAILED": town.post("/check", data={"listing": listings.DETAILED}, headers=HX),
        "no-JS SPARSE": town.post("/check", data={"listing": listings.SPARSE}),
        "no-JS with address": town.post("/check", data={"listing": listings.SPARSE, "address": ADDRESS}),
        "confirmation": town.post("/report", data={"address": ADDRESS, "category": ["heating_hazard"]}),
    }
    for name, resp in reports.items():
        assert resp.status_code == 200, name
        assert DISCLAIMER in resp.text, name


def test_ranking_statement_on_town_building_and_about(signed_in):
    for path in ("/town", BUILDING_URL, "/about"):
        resp = signed_in.get(path)
        assert resp.status_code == 200, path
        assert RANKING_STATEMENT in resp.text, path


# --- 4. About page background facts and source links -------------------------------------------


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[dict] = []
        self._cur: dict | None = None
        self._sr = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a":
            self._cur = {"href": a.get("href"), "target": a.get("target"), "rel": a.get("rel") or "", "sr": ""}
        elif tag == "span" and self._cur is not None and "sr-only" in (a.get("class") or ""):
            self._sr = True

    def handle_endtag(self, tag):
        if tag == "span":
            self._sr = False
        elif tag == "a" and self._cur is not None:
            self.links.append(self._cur)
            self._cur = None

    def handle_data(self, data):
        if self._cur is not None and self._sr:
            self._cur["sr"] += data


def test_about_background_facts_verbatim_and_sources_open_safely(client):
    page = client.get("/about").text
    for item in BACKGROUND:
        assert html.escape(item.fact) in page, item.fact
    parser = _Links()
    parser.feed(page)
    by_href: dict[str, list[dict]] = {}
    for link in parser.links:
        by_href.setdefault(link["href"], []).append(link)
    for item in BACKGROUND:
        for src in item.sources:
            found = by_href.get(src.url)
            assert found, f"no link to {src.url}"
            for link in found:
                assert link["target"] == "_blank", src.url
                rel = link["rel"].split()
                assert "noopener" in rel and "noreferrer" in rel, src.url
                assert link["sr"].strip() == "(opens in a new tab)", src.url


# --- 5. DEMO.md hygiene -----------------------------------------------------------------------

DEMO = (ROOT / "DEMO.md").read_text()
ROUTE_RE = re.compile(r"(?<![\w/.])(/(?:check|report|town|about|health)[a-z/?=0-9.]*)")
FILE_RE = re.compile(r"(?<![\w/.])((?:samples|scripts|data)/[\w./-]+)")
GENERATED = {"data/boston.sqlite", "data/app.sqlite"}


def _demo_section(heading: str) -> str:
    start = DEMO.index(heading)
    nxt = DEMO.find("\n## ", start + len(heading))
    return DEMO[start: nxt if nxt != -1 else len(DEMO)]


def test_demo_report_step_uses_made_up_address():
    table = _demo_section("## Script")
    rows = [l for l in table.splitlines() if l.startswith("|") and "Report" in l.split("|")[2]]
    assert len(rows) == 1, rows
    row = rows[0]
    assert "41 Parker Hill" not in row
    assert "12 Example St" in row
    # The address is replaced before submitting.
    assert row.index("12 Example St") < row.rindex("Submit")


def test_demo_checklist_never_says_to_report_parker_hill():
    checklist = _demo_section("## Pre-demo checklist")
    items = re.split(r"\n- \[ \] ", checklist)
    for item in items:
        if "41 Parker Hill" in item:
            assert "Never submit" in item, item
            assert not re.search(r"(?<!Never )submit (a )?(demo )?report for (it|41 Parker Hill)", item, re.I)
    # The fallbacks don't suggest filling the real table with reports either.
    fallbacks = _demo_section("## Fallbacks")
    assert "41 Parker Hill" not in fallbacks


def test_demo_routes_exist(town):
    # FastAPI's included routers don't expose flat paths, so request each route instead.
    routes = {m.rstrip(".") for m in ROUTE_RE.findall(DEMO)}
    assert {"/health", "/check?sample=1", "/town/login"} <= routes
    missing = []
    for r in sorted(routes):
        resp = town.get(r, follow_redirects=False)
        if resp.status_code in (404, 405):
            missing.append((r, resp.status_code))
    assert not missing, f"DEMO.md mentions routes that don't exist: {missing}"


def test_demo_file_paths_exist():
    paths = {m.rstrip(".") for m in FILE_RE.findall(DEMO)}
    assert "samples/sample_lease.pdf" in paths
    missing = [p for p in sorted(paths) if p not in GENERATED and not (ROOT / p).exists()]
    assert not missing, f"DEMO.md mentions files that don't exist: {missing}"


# --- 6. docs/DEPLOY.md script modules ---------------------------------------------------------


def test_deploy_doc_script_modules_exist():
    text = (ROOT / "docs" / "DEPLOY.md").read_text()
    modules = set(re.findall(r"python -m scripts\.(\w+)", text))
    assert modules
    missing = [m for m in sorted(modules) if not (ROOT / "scripts" / f"{m}.py").exists()]
    assert not missing, f"DEPLOY.md mentions missing modules: {missing}"


# --- 7. Off-topic and privacy regression ------------------------------------------------------


def test_report_email_is_stored_redacted(client, app_db):
    resp = client.post(
        "/report",
        data={
            "address": "12 Example St, Amherst, MA 01002",
            "category": ["smoke_alarm"],
            "description": "Alarm has no battery. Email me at tenant.person@example.com please.",
        },
    )
    assert resp.status_code == 200
    with sqlite3.connect(app_db) as con:
        (desc,) = con.execute("SELECT description FROM reports").fetchone()
    assert "[email removed]" in desc
    assert "tenant.person" not in desc and "example.com" not in desc


@pytest.mark.parametrize("headers", [HX, {}], ids=["htmx", "no-js"])
def test_recipe_rejected_without_ai_call(client, headers):
    fake = FakeClient()  # no queued responses: any call would raise IndexError
    app.dependency_overrides[get_ai_client] = lambda: fake
    resp = client.post("/check", data={"listing": listings.RECIPE}, headers=headers)
    assert resp.status_code in (200, 422)
    assert NOT_A_LISTING_MESSAGE in _visible_text(resp.text)
    assert "Chocolate chip" not in resp.text  # pasted text isn't echoed back
    assert fake.calls == []


def test_demo_cleanup_removes_demo_report_and_status(tmp_path):
    """The DEMO.md cleanup deletes the demo rows from reports and building_status, nothing else."""
    from app.db import init_db
    from app.services.building_status import set_status

    checklist = _demo_section("## Pre-demo checklist")
    cleanup = next(i for i in re.split(r"\n- \[ \] ", checklist) if "After the demo" in i)
    assert "reports" in cleanup and "building_status" in cleanup
    commands = re.findall(r"`([^`]*12 EXAMPLE ST[^`]*)`", cleanup)
    sqlite_cli = next(c for c in commands if c.startswith("sqlite3 "))
    docker = next(c for c in commands if c.startswith("docker exec "))
    assert "building_key LIKE '12 EXAMPLE ST%'" in sqlite_cli
    assert "address_key LIKE '12 EXAMPLE ST%'" in sqlite_cli

    db = tmp_path / "app.sqlite"
    init_db(db)
    with sqlite3.connect(db) as con:
        for key in ("12 EXAMPLE ST 01002", "LONDON KEEP"):
            con.execute(
                """INSERT INTO reports (address_input, address_key, category, created_at, is_simulated)
                   VALUES ('x', ?, 'other', '2026-10-01', 0)""",
                (key,),
            )
    set_status(db, "12 EXAMPLE ST 01002", "scheduled")
    set_status(db, LONDON_KEY, "scheduled")

    # Run the Docker one-liner's Python against the temp DB (same statements as the CLI form).
    code = re.search(r'python -c "(.*)"$', docker).group(1).replace('\\"', '"')
    code = code.replace("/data/app.sqlite", str(db))
    exec(compile(code, "demo-cleanup", "exec"), {})

    with sqlite3.connect(db) as con:
        keys = [r[0] for r in con.execute("SELECT address_key FROM reports")]
        statuses = [r[0] for r in con.execute("SELECT building_key FROM building_status")]
    assert keys == ["LONDON KEEP"]
    assert statuses == [LONDON_KEY]
