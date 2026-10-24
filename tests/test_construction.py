"""Nearby construction: classification, the construction table, runtime lookup, and the card."""

import io
import re
import sqlite3

import pandas as pd
import pytest

from app.main import app
from app.services.boston import context_for_address, get_boston_db
from app.services.building_questions import construction_questions
from app.services.construction import (
    AMHERST_PERMIT_PORTAL,
    construction_context,
    haversine_m,
    is_amherst,
    nearby_construction,
    round_distance,
)
from scripts import construction
from scripts.preprocess_boston import PERMIT_READ_COLUMNS
from tests.fixtures.boston_csv import PERMITS_CSV
from tests.fixtures.boston_db import build_fixture_db
from tests.fixtures.listings import SPARSE

HX = {"HX-Request": "true"}
LONDON = "182 London St 02128"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    return build_fixture_db(tmp_path_factory.mktemp("con") / "boston.sqlite")


def _rows(db):
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute("SELECT * FROM construction ORDER BY lat")]


# --- Block labels and classification ------------------------------------------------------

@pytest.mark.parametrize(
    "address, label",
    [
        ("182 London ST", "100 block of London St"),
        ("31-33 Boardman ST", "1-99 block of Boardman St"),
        ("1250 Commonwealth AV", "1200 block of Commonwealth Ave"),
        ("12A Mission Park DR", "1-99 block of Mission Park Dr"),
        ("Main ST", None),
        (None, None),
    ],
)
def test_block_label_never_has_house_number(address, label):
    assert construction.block_label(address) == label


@pytest.mark.parametrize(
    "permittype, worktype, value, expected",
    [
        ("Erect/New Construction", "ERECT", None, ("new_construction", "New building")),
        ("Foundation Permit", "OTHER", 1.0, ("new_construction", "Foundation for a new building")),
        ("Amendment to a Long Form", "ERECT", None, ("new_construction", "New building")),
        ("Long Form/Alteration Permit", "INTREN", 150_000, ("major_work", "Major interior renovation")),
        ("Long Form/Alteration Permit", "ADDITION", 100_000, ("major_work", "Addition to a building")),
        ("Long Form/Alteration Permit", "INTREN", 99_999, None),
        ("Long Form/Alteration Permit", "INTREN", None, None),
        ("Long Form/Alteration Permit", "CHGOCC", 5_000_000, None),
        ("Short Form Bldg Permit", "RAZE", 1.0, ("major_work", "Demolition")),
        ("Short Form Bldg Permit", "INTDEM", 900_000, None),
        ("Short Form Bldg Permit", "INTREN", 900_000, None),
        ("Electrical Permit", "ELECTRICAL", 900_000, None),
    ],
)
def test_classify(permittype, worktype, value, expected):
    assert construction.classify(permittype, worktype, value) == expected


# --- Construction table -------------------------------------------------------------------

def test_construction_table_contents(db):
    rows = _rows(db)
    # C1+C2 (same site, deduped to the newer building permit), C3, C5 (the London St building
    # itself, kept in the table but never shown for it), C7 (demolition, far away).
    # Dropped: C4 (under the value threshold), C6 (older than 24 months), C8 (partial demo).
    assert [(r["block_label"], r["kind"], r["work_label"], r["issued_month"]) for r in rows] == [
        ("100 block of London St", "major_work", "Addition to a building", "2026-04"),
        ("100 block of London St", "new_construction", "New building", "2026-03"),
        ("200 block of London St", "major_work", "Major interior renovation", "2025-06"),
        ("300 block of London St", "major_work", "Demolition", "2026-05"),
    ]
    assert {r["parcel_id"] for r in rows} == {"0106069000", "0106070000", "0106080000", "0106110000"}


def test_construction_table_has_no_pii_or_exact_address(db):
    with sqlite3.connect(db) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(construction)")}
        text = " ".join(str(v) for row in con.execute("SELECT * FROM construction") for v in row).upper()
        indexes = [r[0] for r in con.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='construction'")]
    assert cols == {"parcel_id", "lat", "lon", "block_label", "kind", "work_label", "issued_month", "status"}
    for marker in ("SECRET", "TEST APPLICANT", "2345678", "2,345,678", "184 LONDON", "230 LONDON", "C1"):
        assert marker not in text
    assert any("lat" in sql and "lon" in sql for sql in indexes)


def test_construction_whitelist_excludes_free_text_and_money_fields():
    forbidden = {"applicant", "comments", "description", "total_fees"}
    assert not forbidden & set(construction.CONSTRUCTION_COLUMNS)
    assert not forbidden & set(PERMIT_READ_COLUMNS)


def test_build_construction_never_stores_valuation():
    permits = pd.read_csv(io.StringIO(PERMITS_CSV), dtype=str, usecols=PERMIT_READ_COLUMNS)
    out = construction.build_construction(permits, pd.Series(dtype="string"), pd.Series(dtype="string"), "2026-10-24")
    assert "declared_valuation" not in out.columns
    assert not out.empty


# --- Runtime lookup -----------------------------------------------------------------------

def test_distance_helpers():
    assert round(haversine_m(42.375, -71.037, 42.3752, -71.037)) == 22
    assert round_distance(22) == 50
    assert round_distance(167) == 150
    assert round_distance(176) == 200


def test_nearby_excludes_own_parcel_and_far_sites(db):
    sites = nearby_construction(42.375, -71.037, db, exclude_parcels=("0106069000",))
    assert [(s.block_label, s.distance_m, s.next_door) for s in sites] == [
        ("100 block of London St", 50, True),
        ("200 block of London St", 150, False),
    ]
    # Without the exclusion the building's own permit would be first.
    assert nearby_construction(42.375, -71.037, db)[0].work_label == "Addition to a building"
    assert len(nearby_construction(42.375, -71.037, db, limit=1)) == 1
    assert nearby_construction(42.375, -71.037, db, radius_m=1000)[-1].work_label == "Demolition"


def test_context_for_rental_building(db):
    ctx = construction_context(LONDON, context_for_address(LONDON, db), db, snapshot_date="2026-10-24")
    assert ctx.kind == "boston" and ctx.any_next_door
    assert [s.work_label for s in ctx.sites] == ["New building", "Major interior renovation"]


def test_context_for_non_rental_still_shown(db):
    # Not building history, so it's shown for any matched address. Nothing near 10 Oak Ave.
    ctx = construction_context("10 Oak Ave 02122", context_for_address("10 Oak Ave 02122", db), db)
    assert ctx.kind == "boston" and ctx.sites == ()


@pytest.mark.parametrize("address", ["999 London St 02128", "10 Oak Ave"])
def test_no_construction_for_area_or_unmatched(db, address):
    assert construction_context(address, context_for_address(address, db), db) is None


def test_amherst_and_other_towns(db):
    for addr in ("12 Example St, Amherst, MA 01002", "5 Example Rd Amherst MA", "1 Example Ave 01003"):
        assert is_amherst(addr), addr
        ctx = construction_context(addr, context_for_address(addr, db), db)
        assert ctx.kind == "amherst" and ctx.portal_url == AMHERST_PERMIT_PORTAL
    assert not is_amherst("10 Amherst St, Boston 02134")
    other = "4 Example St, Worcester, MA 01609"
    assert construction_context(other, context_for_address(other, db), db).kind == "other"
    assert construction_context("", None, db) is None


def test_construction_question(db):
    ctx = construction_context(LONDON, context_for_address(LONDON, db), db)
    (q,) = construction_questions(ctx)
    assert "next door to this building" in q.question
    assert "smoke alarms" in q.question and "exits" in q.question
    assert q.source_id == "nfpa_construction" and q.relation == "based_on"
    assert q.citation == "Based on guidance from the National Fire Protection Association"
    oak = construction_context("10 Oak Ave 02122", context_for_address("10 Oak Ave 02122", db), db)
    assert construction_questions(oak) == []
    assert construction_questions(None) == []


# --- Route --------------------------------------------------------------------------------

def _post(client, db, address):
    app.dependency_overrides[get_boston_db] = lambda: db
    return client.post("/check", data={"listing": SPARSE, "address": address}, headers=HX).text


def test_card_for_rental_building(client, db):
    html = _post(client, db, "182 London St, East Boston 02128")
    assert "Construction nearby" in html
    assert "100 block of London St" in html and "200 block of London St" in html
    assert "next door" in html and "about 150 m away" in html
    assert "permit issued 2026-03" in html
    # Never the exact address of a construction site, its applicant, or valuation.
    for leaked in ("184 London", "230 London", "TEST APPLICANT", "SECRET", "2,345,678", "Addition to a building"):
        assert leaked not in html
    assert "How is the site secured" in html
    assert "Based on guidance from the National Fire Protection Association" in html
    assert "NFPA construction site fire safety fact sheet" in html  # cited sources list
    assert "Sites are shown by block, not exact address." in html


def test_card_for_amherst(client, db):
    html = _post(client, db, "12 Example St, Amherst, MA 01002")
    assert "Construction nearby" in html
    m = re.search(r'<a href="https://amherstma\.portal\.opengov\.com"[^>]*>(.*?)</a>', html, re.S)
    assert m and "(opens in a new tab)" in m.group(1)
    assert 'rel="noopener noreferrer"' in m.group(0) and 'target="_blank"' in m.group(0)
    assert "Ask the landlord whether there is construction" in html


def test_card_for_other_town(client, db):
    html = _post(client, db, "4 Example St, Worcester, MA 01609")
    assert "town&#39;s building department" in html or "town's building department" in html


def test_no_card_without_boston_point(client, db):
    assert "Construction nearby" not in _post(client, db, "999 London St 02128")


def test_card_copy_rules(client, db):
    html = _post(client, db, "182 London St, East Boston 02128")
    card = html[html.index('id="construction-heading"'):]
    card = card[: card.index("</section>")]
    text = re.sub(r"<[^>]+>", " ", card)
    assert "\u2014" not in text and "!" not in text
    assert not re.search(r"\b(is|are) safe\b", text)
