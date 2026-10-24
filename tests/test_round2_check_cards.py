"""Round 2: construction and census cards end to end through POST /check (HTMX and full page),
plus copy, heading-order, and disclaimer checks on every new card."""

import html as htmllib
import re
from html.parser import HTMLParser

import pytest

from app.content.copy import DISCLAIMER
from app.main import CONTENT_SECURITY_POLICY, app
from app.services.boston import get_boston_db
from tests.fixtures.boston_db import build_fixture_db
from tests.fixtures.listings import SPARSE

HX = {"HX-Request": "true"}
LONDON = "182 London St, East Boston 02128"
AMHERST = "12 Example St, Amherst, MA 01002"
AMHERST_NO_ZIP = "12 Example St, Amherst, MA"
WORCESTER = "4 Example St, Worcester, MA 01609"
OAK = "10 Oak Ave 02122"  # matched Boston address, no census row for 02122

# House numbers of the fixture construction permits (tests/fixtures/boston_csv.py C1-C8).
# None of them may ever appear as an exact address.
SITE_NUMBERS = ("184", "186", "188", "190", "200", "230", "300")
NFPA_CITATION = "Based on guidance from the National Fire Protection Association"
NFPA_NAME = "NFPA construction site fire safety fact sheet"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    return build_fixture_db(tmp_path_factory.mktemp("round2_cards") / "boston.sqlite")


def _post(client, db, address, htmx=True):
    app.dependency_overrides[get_boston_db] = lambda: db
    resp = client.post(
        "/check", data={"listing": SPARSE, "address": address}, headers=HX if htmx else {}
    )
    assert resp.status_code == 200
    return resp


def _section(page: str, heading_id: str) -> str | None:
    """The <section> that holds the heading with this id, or None."""
    i = page.find(f'id="{heading_id}"')
    if i == -1:
        return None
    start = page.rfind("<section", 0, i)
    end = page.index("</section>", i)
    return page[start : end + len("</section>")]


def _text(fragment: str) -> str:
    return htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment)))


class _Headings(HTMLParser):
    def __init__(self):
        super().__init__()
        self.levels: list[int] = []

    def handle_starttag(self, tag, attrs):
        if re.fullmatch(r"h[1-6]", tag):
            self.levels.append(int(tag[1]))


def _heading_levels(page: str) -> list[int]:
    p = _Headings()
    p.feed(page)
    return p.levels


MODES = pytest.mark.parametrize("htmx", [True, False], ids=["htmx", "full_page"])


# --- 1. Construction card end to end ----------------------------------------------------------


@MODES
def test_boston_rental_near_site_shows_block_level_card(client, db, htmx):
    page = _post(client, db, LONDON, htmx).text
    card = _section(page, "construction-heading")
    assert card is not None
    text = _text(card)
    assert "100 block of London St" in text and "200 block of London St" in text
    assert "next door" in text
    # Never an exact house number from a fixture permit, anywhere on the page.
    for n in SITE_NUMBERS:
        assert not re.search(rf"\b{n}\s+London\b", _text(page), re.I), n
        if int(n) % 100:  # 200 and 300 are also block starts ("200 block of London St")
            assert not re.search(rf"\b{n}\b", text), n
    # The construction question cites NFPA guidance, and NFPA is linked and in the sources list.
    assert "Question about nearby construction" in text
    assert NFPA_CITATION in text
    assert NFPA_NAME in text
    sources = _section(page, "sources-heading")
    assert sources is not None and NFPA_NAME in _text(sources)


@MODES
def test_amherst_shows_portal_link(client, db, htmx):
    card = _section(_post(client, db, AMHERST, htmx).text, "construction-heading")
    assert card is not None
    m = re.search(r'<a href="https://amherstma\.portal\.opengov\.com"[^>]*>(.*?)</a>', card, re.S)
    assert m, card
    assert "(opens in a new tab)" in m.group(1)
    assert 'rel="noopener noreferrer"' in m.group(0)
    assert 'target="_blank"' in m.group(0)


@MODES
def test_other_town_shows_building_department_line(client, db, htmx):
    card = _section(_post(client, db, WORCESTER, htmx).text, "construction-heading")
    assert card is not None
    text = _text(card)
    assert "only has construction permit data for Boston" in text
    assert "ask the town's building department about permits nearby" in text
    assert "amherstma.portal" not in card


@MODES
def test_blank_address_shows_no_construction_or_census_card(client, db, htmx):
    page = _post(client, db, "", htmx).text
    assert "Fire-safety report" in page
    assert 'id="construction-heading"' not in page and "Construction nearby" not in page
    assert 'id="census-heading"' not in page and "Area housing" not in page


# --- 1. Census card -----------------------------------------------------------------------------


@MODES
@pytest.mark.parametrize("address, zip_code", [(LONDON, "02128"), (AMHERST, "01002")])
def test_census_card_links_to_zip_page(client, db, htmx, address, zip_code):
    card = _section(_post(client, db, address, htmx).text, "census-heading")
    assert card is not None
    hrefs = re.findall(r'href="([^"]+)"', card)
    # The smoke alarm rules source for the building-age note, then the public Data Commons
    # place page for the ZIP. Nothing else, and no address in any URL.
    from app.content.sources import SOURCES

    assert hrefs == [SOURCES["smoke_alarm_rules"].url, f"https://datacommons.org/place/zip/{zip_code}"]
    assert f"ZIP code {zip_code}" in _text(card)


@MODES
@pytest.mark.parametrize("address", [OAK, WORCESTER, AMHERST_NO_ZIP, "999 London St 02128"])
def test_census_card_only_when_census_zip_has_the_zip(client, db, htmx, address):
    # 02122, 01609, a missing ZIP, and 02128 via area context. Only 02128 is in census_zip.
    page = _post(client, db, address, htmx).text
    if address.endswith("02128"):
        assert _section(page, "census-heading") is not None
    else:
        assert _section(page, "census-heading") is None
        assert "datacommons.org" not in page


def test_census_card_absent_when_table_missing(client, tmp_path):
    no_census = build_fixture_db(tmp_path / "nocensus.sqlite", with_census=False)
    page = _post(client, no_census, LONDON).text
    assert "Construction nearby" in page  # construction still shown
    assert _section(page, "census-heading") is None


# --- 2. Copy rules, headings, disclaimer on every new card -------------------------------------

CARD_CASES = [
    (LONDON, "construction-heading"),
    (AMHERST, "construction-heading"),
    (WORCESTER, "construction-heading"),
    (OAK, "construction-heading"),  # Boston, no sites nearby
    (LONDON, "census-heading"),
    (AMHERST, "census-heading"),
]
UNSAFE_CLAIMS = re.compile(r"\b(safe|safer|safest|compliant|compliance|up to code|meets code)\b", re.I)


@MODES
@pytest.mark.parametrize("address, heading_id", CARD_CASES)
def test_card_copy_rules(client, db, htmx, address, heading_id):
    card = _section(_post(client, db, address, htmx).text, heading_id)
    assert card is not None, (address, heading_id)
    text = _text(card)
    assert "\u2014" not in text and "&mdash;" not in card
    assert "!" not in text
    assert not UNSAFE_CLAIMS.search(text), UNSAFE_CLAIMS.search(text)
    # Every external link in the card opens safely and says so.
    for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", card, re.S):
        if 'href="https://' in m.group(1):
            assert 'target="_blank"' in m.group(1) and 'rel="noopener noreferrer"' in m.group(1)
            assert "(opens in a new tab)" in m.group(2)


@MODES
@pytest.mark.parametrize("address", [LONDON, AMHERST, WORCESTER, OAK, ""])
def test_headings_in_order_and_disclaimer_present(client, db, htmx, address):
    resp = _post(client, db, address, htmx)
    page = resp.text
    levels = _heading_levels(page)
    if htmx:
        assert levels[0] == 2
    else:
        assert levels.count(1) == 1 and levels.index(1) < levels.index(2)
    for prev, cur in zip(levels, levels[1:]):
        assert cur <= prev + 1, f"heading skip h{prev} -> h{cur}: {levels}"
    # New cards are h3 sections under the h2 report heading, before the sources list.
    for hid in ("construction-heading", "census-heading"):
        if f'id="{hid}"' in page:
            assert re.search(rf'<h3 id="{hid}"', page)
            assert page.index(f'id="{hid}"') < page.index('id="sources-heading"')
    assert page.count(DISCLAIMER) == 1
    assert page.index('id="sources-heading"') < page.index(DISCLAIMER)
    assert resp.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
