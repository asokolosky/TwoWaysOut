import re
import sqlite3

import pytest

from app.main import app
from app.services.boston import context_for_address, get_boston_db
from app.services.building_questions import questions_for_context
from app.services.fire_categories import categorize, display_description
from app.services.rules_analyzer import analyze
from tests.fixtures.boston_db import build_fixture_db
from tests.fixtures.listings import SPARSE

HX = {"HX-Request": "true"}


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    return build_fixture_db(tmp_path_factory.mktemp("bos") / "boston.sqlite")


# --- Category tagging against real description strings -----------------------------------

@pytest.mark.parametrize(
    "description, category",
    [
        ("Heat - Excessive, Insufficient", "heating"),
        ("Electrical", "electrical"),
        ("The owner shall provide, install, and maintain in operable condition smoke detectors and carbon monoxide alarms in every residence is required", "smoke_alarms"),
        ("Unsatisfactory Utilities - Electrical, Plumbing", "electrical"),
        ("Egress", "egress"),
        ("No person shall cause obstruction of any means of egress or passageway.", "egress"),
        ("Every residence and unit shall have a sufficient number of egresses as will allow for the safe passage of all people.", "egress"),
        ("Failure to provide heat as required by 105 CMR 410.180 or improper venting or use of a space heater or water heater", "heating"),
        ("Failure to provide a smoke detector or carbon monoxide alarm required by 105 CMR 410.330.", "smoke_alarms"),
        ("Carbon Monoxide", "smoke_alarms"),
        ("Means of Egress", "egress"),
        ("Number of Exits or Exit Access", "egress"),
        ("Fire Protection Systems", "fire_protection"),
        ("Automatic Sprinkler System", "fire_protection"),
        ("Fire Alarm & Detection Systems", "smoke_alarms"),
        ("Guarding of Live parts", "electrical"),
        ("Electrical Work w/out a Permit", "electrical"),
        ("No temporary wiring shall be used. No wiring shall extend through a doorway or other opening in a structural element.", "electrical"),
        ("All devices that combust fuel shall be properly vented to the outdoors.", "heating"),
    ],
)
def test_fire_categories(description, category):
    assert categorize(description) == category


@pytest.mark.parametrize(
    "description",
    [
        "Improper storage trash: res",
        "Rodent Activity",
        "Unsafe and Dangerous",
        "Failure to Obtain Permit",
        "No Utilities Residential - Electricity",
        "The owner shall provide the electricity or gas used in each dwelling unit unless: the utility is seperated and there is a written rental agreement",
        "Metering of Electricity, Gas and Water - Owner shall provide Electricity and Gas",
        "Shutoff and/or failure to restore electricity, gas, or water.",
        "Location of Exhaust Outlets",
        "Roof, foundation, or other structural defects in violation of 105 CMR 410.500",
        None,
        "",
    ],
)
def test_not_fire_related(description):
    assert categorize(description) is None


@pytest.mark.parametrize(
    "raw, shown",
    [
        ("Failure to provide a smoke detector or carbon monoxide alarm required by 105 CMR 410.330.", "Failure to provide a smoke detector or carbon monoxide alarm"),
        ("Failure to provide heat as required by 105 CMR 410.180 or improper venting", "Failure to provide heat"),
        ("Heat - Excessive, Insufficient", "Heat - Excessive, Insufficient"),
    ],
)
def test_display_description_drops_section_numbers(raw, shown):
    assert display_description(raw) == shown
    assert not re.search(r"CMR|§|\d{3}\.\d", display_description(raw))


# --- Preprocessing ------------------------------------------------------------------------

def test_no_pii_in_any_table(db):
    with sqlite3.connect(db) as con:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tables:
            cols = {r[1].lower() for r in con.execute(f"PRAGMA table_info({t})")}
            assert not cols & {
                "owner", "applicant", "comments", "contact_addr1", "contact_addr2", "contact_city",
                "contact_state", "contact_zip", "mail_addressee", "mail_street_address", "mail_city",
                "mail_state", "mail_zip_code", "declared_valuation", "total_fees",
            }, t
            for row in con.execute(f"SELECT * FROM {t}"):
                text = " ".join(str(v) for v in row).upper()
                assert "TEST OWNER" not in text and "TEST APPLICANT" not in text and "SECRET" not in text, t


def test_records_tagged_rental_only_and_rolled_up(db):
    with sqlite3.connect(db) as con:
        rows = con.execute("SELECT parcel_id, source, kind, category, status FROM records ORDER BY parcel_id, date").fetchall()
    parcels = {r[0] for r in rows}
    # 10 Oak Ave is an owner-occupied single family: not a rental, so no building records.
    assert "1500001000" not in parcels
    # Condo unit 0100010004 rolls up to the building 0100010000.
    assert "0100010000" in parcels and "0100010004" not in parcels
    london = [r for r in rows if r[0] == "0106069000"]
    # Trash and utility-billing records are dropped; "Unsafe and Dangerous" isn't fire-specific.
    assert sorted(r[3] for r in london) == ["egress", "egress", "fire_protection", "heating", "smoke_alarms"]
    # The ISD egress violation came in on a unit-level SAM ID (2) and joined to the building.
    assert ("0106069000", "isd_violations", "violation", "egress", "Open") in london


def test_permits_kept_by_kind(db):
    with sqlite3.connect(db) as con:
        kinds = con.execute("SELECT kind FROM permits WHERE parcel_id='0106069000' ORDER BY issued_date").fetchall()
    assert [k[0] for k in kinds] == ["electrical", "fire_alarm"]  # plumbing dropped


def test_permits_table_rentals_only(db):
    # P4 is an electrical permit at 10 Oak Ave (owner-occupied single family): not stored.
    with sqlite3.connect(db) as con:
        parcels = {r[0] for r in con.execute("SELECT DISTINCT parcel_id FROM permits")}
    assert "1500001000" not in parcels
    assert parcels == {"0106069000"}


def test_area_stats_cover_all_buildings(db):
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        z = con.execute("SELECT * FROM area_stats WHERE level='zip' AND area_key='02122'").fetchone()
        city = con.execute("SELECT * FROM area_stats WHERE level='city'").fetchone()
    # The non-rental's electrical complaint still counts toward the area.
    assert z["n_electrical"] == 1
    assert city["since"] == "2025-10-24"
    # The 2024 egress complaint is older than 12 months, so it's excluded.
    assert city["n_egress"] == 1


# --- Building context ---------------------------------------------------------------------

def test_rental_gets_building_history(db):
    ctx = context_for_address("182 London St 02128", db)
    assert ctx.kind == "building"
    h = ctx.history
    assert h.total_records == 5
    assert h.open_violations == 1
    assert h.first_date == "2024-03-02"
    assert h.snapshot_date == "2026-10-24"
    c = h.counts_by_category
    assert (c["egress"].violations, c["egress"].complaints, c["egress"].open) == (1, 1, 1)
    assert [p.kind for p in h.permits] == ["fire_alarm", "electrical"]
    assert h.recent[0].date == "2026-09-01"


def test_non_rental_falls_back_to_area(db):
    ctx = context_for_address("10 Oak Ave 02122", db)
    assert ctx.kind == "area"
    assert "don't list this building as a rental" in ctx.reason
    assert ctx.area.area.level == "zip" and ctx.area.area.area_key == "02122"
    assert ctx.history is None


def test_unmatched_boston_address_uses_zip_area(db):
    ctx = context_for_address("999 London St 02128", db)
    assert ctx.kind == "area"
    assert "couldn't find that address" in ctx.reason


@pytest.mark.parametrize(
    "address, phrase",
    [
        ("12 Example St, Amherst, MA 01002", "only available for Boston"),
        ("10 Oak Ave", "Add the ZIP code"),
        ("999 Nowhere Rd", "couldn't find that address"),
    ],
)
def test_no_context_cases(db, address, phrase):
    ctx = context_for_address(address, db)
    assert ctx.kind == "none" and phrase in ctx.reason


def test_blank_address_no_context(db):
    assert context_for_address("", db) is None


def test_database_without_history_tables(tmp_path):
    path = build_fixture_db(tmp_path / "b.sqlite", with_history=False)
    ctx = context_for_address("182 London St 02128", path)
    assert ctx.kind == "none" and "history isn't loaded" in ctx.reason


# --- Building questions -------------------------------------------------------------------

def test_building_questions(db):
    ctx = context_for_address("182 London St 02128", db)
    qs = questions_for_context(ctx, analyze(SPARSE).questions)
    text = " | ".join(q.question for q in qs)
    assert "1 violation about smoke or carbon monoxide alarms" in text
    assert "1 violation and 1 complaint about exits at this building since 2024, 1 still open" in text
    assert "built in 1910" in text
    # Electrical permit is from 1999: older than 20 years, so ask about wiring.
    assert "no electrical permit" in text
    for q in qs:
        assert not re.search(r"CMR|§", q.question + q.citation)
    # The rule analyzer already asks a CO question, so no duplicate from heat type.
    assert not any(q.source_id == "co_alarm_rules" for q in qs)


def test_heat_type_adds_co_question_when_missing(db):
    ctx = context_for_address("182 London St 02128", db)
    qs = questions_for_context(ctx, existing=[])
    co = [q for q in qs if q.source_id == "co_alarm_rules"]
    assert co and "ht water/steam" in co[0].question.lower()


def test_no_building_questions_for_area_context(db):
    assert questions_for_context(context_for_address("10 Oak Ave 02122", db), []) == []


# --- Route --------------------------------------------------------------------------------

def test_report_shows_building_card(client, db):
    app.dependency_overrides[get_boston_db] = lambda: db
    html = client.post("/check", data={"listing": SPARSE, "address": "182 London St, East Boston 02128"}, headers=HX).text
    assert "Boston building records" in html
    assert "Means of Egress" in html
    assert "1 still open" in html
    assert "Fire alarm work: 1 permit, most recent 2019-04-01" in html
    assert "Questions based on these records" in html
    assert "Snapshot 2026-10-24" in html
    assert "TEST OWNER" not in html


def test_report_uses_address_found_in_listing(client, db):
    app.dependency_overrides[get_boston_db] = lambda: db
    listing = "Sunny 3BR apartment at 182 London St, East Boston, MA 02128. Heat included."
    html = client.post("/check", data={"listing": listing}, headers=HX).text
    assert "found in the listing" in html
    assert "Boston building records" in html


def test_report_shows_area_card(client, db):
    app.dependency_overrides[get_boston_db] = lambda: db
    html = client.post("/check", data={"listing": SPARSE, "address": "10 Oak Ave 02122"}, headers=HX).text
    assert "Neighborhood context" in html
    assert "This is about the area, not this building." in html
    assert "Boston building records" not in html


def test_report_outside_boston(client, db):
    app.dependency_overrides[get_boston_db] = lambda: db
    html = client.post("/check", data={"listing": SPARSE, "address": "12 Example St, Amherst, MA 01002"}, headers=HX).text
    assert "only available for Boston" in html
    assert "Board of Health" in html


def test_rental_with_no_records_never_says_safe(client, db):
    # 9 Mount Vernon St: a non-owner-occupied condo (rental) with no records.
    app.dependency_overrides[get_boston_db] = lambda: db
    html = client.post("/check", data={"listing": SPARSE, "address": "9 Mount Vernon St, Boston 02108"}, headers=HX).text
    assert "Boston building records" in html
    assert "No fire-related violations or complaints on record" in html
    assert "doesn't mean the building is safe" in html
