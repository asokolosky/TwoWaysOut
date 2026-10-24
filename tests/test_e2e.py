"""End to end: student check -> tenant report -> town dashboard -> status, plus page-wide accessibility."""

import html
import re
import sqlite3
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import Settings, get_settings
from app.content.copy import DISCLAIMER, RANKING_STATEMENT
from app.content.report_categories import REPORT_CATEGORIES
from app.main import app
from app.routers.town import get_login_limiter
from app.services.boston import get_boston_db
from app.services.rate_limit import RateLimiter
from tests.fixtures.boston_db import build_fixture_db

PASSWORD = "test-pass"
SECRET = "x" * 40
ADDRESS = "182 London St, East Boston 02128"
LONDON_KEY = "PARCEL 0106069000"
LISTING = (
    "Sunny 3 bedroom apartment for rent at 182 London St, East Boston 02128. "
    "Hardwood floors, laundry in the basement, heat included. Available September 1. "
    "Rent $3,200 per month, first and last plus security deposit."
)
SIM_BUILDINGS = [f"SIM-{i:02d}" for i in range(4)]

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')
REPORT_LINK_RE = re.compile(r'<a href="(/report[^"]*)"[^>]*>\s*Report a problem here')


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
def simulated(app_db):
    cats = list(REPORT_CATEGORIES)
    with sqlite3.connect(app_db) as con:
        for i in range(12):
            con.execute(
                """INSERT INTO simulated_reports (sim_building, ward, rental_type, category, description,
                                                  observed_date, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (SIM_BUILDINGS[i % 4], 1, "3-family", cats[i % len(cats)],
                 "Fictional story", "2026-10-01", "2026-10-02"),
            )
    return app_db


def _main(page: str) -> str:
    return page[page.index("<main"):]


def _real_table(page: str) -> str:
    start = page.index('class="data-table town-table')
    return page[start: page.index("</table>", start)]


def _sim_section(page: str) -> str:
    start = page.index('id="sim-heading"')
    return page[start: page.index('id="how-heading"')]


def _row(table: str, key: str) -> str:
    start = table.index(f'data-building-key="{key}"')
    return table[start: table.index("</tr>", start)]


def _num_cells(row: str) -> list[float]:
    return [float(v) for v in re.findall(r'<td class="py-2 num[^"]*">([\d.]+)</td>', row)]


def test_student_report_to_town_dashboard(town, app_db, simulated):
    # 1. Student pastes a listing (HTMX) and gets a report with Boston records.
    resp = town.post("/check", data={"listing": LISTING}, headers={"HX-Request": "true"})
    assert resp.status_code == 200
    report = resp.text
    assert "<html" not in report  # HTMX partial
    assert DISCLAIMER in report
    assert "Boston building records" in report
    m = REPORT_LINK_RE.search(report)
    assert m, "report has no 'Report a problem here' link"
    link = html.unescape(m.group(1))
    prefilled = parse_qs(urlparse(link).query)["address"][0]
    assert "182 London St" in prefilled and "02128" in prefilled

    # 2. Follow the link: the form is prefilled with the address.
    form = town.get(link)
    assert form.status_code == 200
    assert f'value="{html.escape(prefilled)}"' in form.text

    # 3. Submit several problems; the confirmation shows the matched building.
    thanks = town.post(
        "/report",
        data={
            "address": prefilled,
            "category": ["no_second_exit", "smoke_alarm", "electrical_hazard"],
            "description": "Back stairs are blocked. Call me at 617-555-0100.",
        },
    )
    assert thanks.status_code == 200
    assert "Thanks, your report was received" in thanks.text
    assert "182 LONDON ST" in thanks.text.upper()
    assert DISCLAIMER in thanks.text
    with sqlite3.connect(app_db) as con:
        rows = con.execute("SELECT category, extra_categories, is_simulated, description FROM reports").fetchall()
    assert len(rows) == 1
    category, extra, is_sim, description = rows[0]
    assert is_sim == 0 and category in {"no_second_exit", "smoke_alarm"}
    assert "617-555-0100" not in (description or "")

    # 4. Town staff sign in and see the building in the real table.
    assert town.post("/town/login", data={"password": PASSWORD}, follow_redirects=False).status_code == 303
    dash = town.get("/town").text
    assert RANKING_STATEMENT in dash
    real = _real_table(dash)
    row = _row(real, LONDON_KEY)
    tenant, official, total = _num_cells(row)
    assert tenant > 0
    assert official > 0  # the fixture building has fire-related city records
    assert total == pytest.approx(tenant + official, abs=0.11)

    # Simulated rows are masked, labeled, and never in the real table.
    sim = _sim_section(dash)
    assert sim.count('class="sim-row"') == len(SIM_BUILDINGS)
    assert sim.count('<span class="badge badge-sim">SIMULATED</span>') == len(SIM_BUILDINGS)
    assert "London" not in sim and "02128" not in sim
    for sid in SIM_BUILDINGS:
        assert sid not in real
    assert "SIMULATED" not in real

    # 5. Building detail: set status to scheduled with CSRF; scores don't change.
    detail_url = f"/town/building?key={LONDON_KEY.replace(' ', '%20')}"
    detail = town.get(detail_url).text
    assert f"{tenant:.1f}" in detail and f"{official:.1f}" in detail
    token = CSRF_RE.search(detail).group(1)
    status = town.post(
        "/town/building/status",
        data={"key": LONDON_KEY, "status": "scheduled", "csrf_token": token},
        headers={"HX-Request": "true"},
    )
    assert status.status_code == 200
    assert "status-scheduled" in status.text and "Status saved." in status.text
    row_after = _row(_real_table(town.get("/town").text), LONDON_KEY)
    assert "status-scheduled" in row_after
    assert _num_cells(row_after) == [tenant, official, total]

    # 6. The about page states the ranking sentence and the disclaimer.
    about = town.get("/about")
    assert about.status_code == 200
    assert RANKING_STATEMENT in about.text and DISCLAIMER in about.text


# --- Page-wide accessibility ----------------------------------------------------------------


class _PageParser(HTMLParser):
    """Collects headings, labels, controls, and new-tab links (with their sr-only text)."""

    def __init__(self):
        super().__init__()
        self.html_lang = None
        self.h1 = 0
        self.headings: list[int] = []
        self.skip_link = False
        self.label_for: set[str] = set()
        self.wrapped: set[int] = set()  # controls nested inside a <label>
        self.controls: list[dict] = []
        self.blank_links: list[dict] = []
        self._label_depth = 0
        self._link: dict | None = None
        self._sr_depth = 0
        self._stack: list[str] = []
        self.hidden_depth = 0
        self.live_ids: set[str] = set()
        self.hx_targets: list[str] = []
        self.svgs: list[dict] = []
        self.buttons: list[str] = []
        self._button: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.html_lang = a.get("lang")
        if a.get("aria-live") and a.get("id"):
            self.live_ids.add(a["id"])
        if a.get("hx-target"):
            self.hx_targets.append(a["hx-target"])
        if tag == "svg":
            self.svgs.append(a)
        if tag == "button":
            self._button = [a.get("aria-label") or ""]
        if re.fullmatch(r"h[1-6]", tag):
            self.headings.append(int(tag[1]))
        if tag == "h1":
            self.h1 += 1
        elif tag == "label":
            self._label_depth += 1
            if a.get("for"):
                self.label_for.add(a["for"])
        elif tag in ("input", "select", "textarea"):
            a["_tag"] = tag
            a["_in_label"] = self._label_depth > 0
            a["_aria_hidden"] = self.hidden_depth > 0
            self.controls.append(a)
        elif tag == "a":
            if a.get("href") == "#main":
                self.skip_link = True
            if a.get("target") == "_blank":
                self._link = {"href": a.get("href"), "rel": a.get("rel") or "", "sr": ""}
        if tag == "span" and self._link is not None and "sr-only" in (a.get("class") or ""):
            self._sr_depth = 1
        if tag not in ("input", "br", "img", "meta", "link"):
            self._stack.append((tag, a.get("aria-hidden") == "true"))
            if a.get("aria-hidden") == "true":
                self.hidden_depth += 1

    def handle_endtag(self, tag):
        if tag == "button" and self._button is not None:
            self.buttons.append("".join(self._button).strip())
            self._button = None
        if tag == "label":
            self._label_depth -= 1
        if tag == "span" and self._sr_depth:
            self._sr_depth = 0
        if tag == "a" and self._link is not None:
            self.blank_links.append(self._link)
            self._link = None
        if self._stack and self._stack[-1][0] == tag:
            _, hidden = self._stack.pop()
            if hidden:
                self.hidden_depth -= 1

    def handle_data(self, data):
        if self._button is not None:
            self._button.append(data)
        if self._link is not None and self._sr_depth:
            self._link["sr"] += data


GET_PAGES = ["/", "/check", "/check?sample=1", "/report", "/about", "/town/login"]


@pytest.mark.parametrize("path", GET_PAGES)
def test_every_page_basic_accessibility(town, path):
    resp = town.get(path)
    assert resp.status_code == 200, path
    _assert_page_accessible(path, resp.text)


def test_other_full_pages_accessibility(town, simulated):
    # No-JS report page, the report confirmation, and the signed-in town pages.
    pages = {
        "POST /check (no JS)": town.post("/check", data={"listing": LISTING}).text,
        "POST /report": town.post("/report", data={"address": ADDRESS, "category": ["blocked_exit"]}).text,
    }
    assert town.post("/town/login", data={"password": PASSWORD}, follow_redirects=False).status_code == 303
    pages["/town"] = town.get("/town").text
    pages["/town/building"] = town.get(f"/town/building?key={LONDON_KEY.replace(' ', '%20')}").text
    pages["/town/simulated"] = town.get(f"/town/simulated/{SIM_BUILDINGS[0]}").text
    missing = town.get("/town/building?key=PARCEL%200000000000")
    assert missing.status_code == 404
    pages["/town/building (not found)"] = missing.text
    for name, page in pages.items():
        _assert_page_accessible(name, page)
    assert DISCLAIMER in pages["POST /check (no JS)"] and DISCLAIMER in pages["POST /report"]


def _assert_page_accessible(path: str, page: str) -> None:
    p = _PageParser()
    p.feed(page)
    assert p.html_lang == "en"
    assert p.h1 == 1, f"{path} has {p.h1} h1 elements"
    assert p.headings[0] == 1, f"{path}: first heading is h{p.headings[0]}"
    for prev, cur in zip(p.headings, p.headings[1:]):
        assert cur <= prev + 1, f"{path}: heading jumps from h{prev} to h{cur}"
    assert p.skip_link
    for c in p.controls:
        if c.get("type") == "hidden" or c["_aria_hidden"]:
            continue
        labeled = (
            (c.get("id") and c["id"] in p.label_for)
            or c["_in_label"]
            or c.get("aria-label")
            or c.get("aria-labelledby")
        )
        assert labeled, f"{path}: unlabeled control {c}"
    for link in p.blank_links:
        assert "(opens in a new tab)" in link["sr"], f"{path}: {link['href']} lacks new-tab text"
        assert "noopener" in link["rel"]
    for btn in p.buttons:
        assert btn, f"{path}: button without text"
    for svg in p.svgs:
        decorative = svg.get("aria-hidden") == "true"
        named = svg.get("role") == "img" and svg.get("aria-label")
        assert decorative or named, f"{path}: svg is neither aria-hidden nor labeled"
    for target in p.hx_targets:
        assert target.startswith("#") and target[1:] in p.live_ids, (
            f"{path}: HTMX target {target} is not an aria-live region"
        )
    assert "In an emergency, call 911." in page  # footer note on every page


def test_report_form_has_911_note(town):
    assert "If there's a fire or immediate danger, call 911." in town.get("/report").text


def test_about_page_content(town):
    page = town.get("/about").text
    main = _main(page)
    assert 'href="/about"' in page  # header nav
    assert "Olympia Place" in main
    assert "Background" in main
    # Each background fact links to its public source.
    assert "U.S. Fire Administration, Campus Fire Fatalities" in main
    assert "Figures as cited by the project" not in main
    for href in ('href="/check"', 'href="/report"', 'href="/town"'):
        assert href in main
    from app.content.sources import SOURCES
    for s in SOURCES.values():
        assert html.escape(s.name) in main and html.escape(s.url) in main
    assert main.count("(opens in a new tab)") >= len(SOURCES)
    assert "Owner names" in main
    assert RANKING_STATEMENT in main and DISCLAIMER in main
    text = re.sub(r"<[^>]+>", " ", main)
    assert "\u2014" not in text and "!" not in text
