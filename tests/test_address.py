import io
import sqlite3

import pandas as pd
import pytest

from app.services.address import lookup
from app.services.address_normalize import parse_address, street_key
from scripts.preprocess_boston import (
    ASSESSMENT_COLUMNS,
    SAM_COLUMNS,
    build_addresses,
    build_properties,
    classify,
    write_db,
)
from tests.fixtures.boston_csv import ASSESSMENT_CSV, SAM_CSV

@pytest.fixture(scope="module")
def db(tmp_path_factory):
    # Read exactly like the real script: only whitelisted columns.
    sam = pd.read_csv(io.StringIO(SAM_CSV), dtype=str, usecols=SAM_COLUMNS)
    assess = pd.read_csv(io.StringIO(ASSESSMENT_CSV), dtype=str, usecols=ASSESSMENT_COLUMNS)
    path = tmp_path_factory.mktemp("data") / "boston.sqlite"
    write_db(build_addresses(sam), build_properties(assess), path, "2026-10-24")
    return path


# --- Normalizer ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, key",
    [
        ("London St", "LONDON ST"),
        ("london street", "LONDON ST"),
        ("LONDON ST.", "LONDON ST"),
        ("Commonwealth Avenue", "COMMONWEALTH AVE"),
        ("Commonwealth Av", "COMMONWEALTH AVE"),
        ("East Broadway", "E BROADWAY"),
        ("Mount Vernon Street", "MT VERNON ST"),
        ("Mt. Vernon St", "MT VERNON ST"),
        ("Savin Hill Terrace", "SAVIN HILL TER"),
    ],
)
def test_street_key(raw, key):
    assert street_key(raw) == key


@pytest.mark.parametrize(
    "raw, number, lo, hi, street, zip_, place",
    [
        ("182 London St 02128", "182", 182, 182, "LONDON ST", "02128", None),
        ("182 London Street, East Boston, MA", "182", 182, 182, "LONDON ST", None, "EAST BOSTON"),
        ("182 London St Apt 2, East Boston, MA 02128-1234", "182", 182, 182, "LONDON ST", "02128", "EAST BOSTON"),
        ("182 London St #2", "182", 182, 182, "LONDON ST", None, None),
        ("182 London St Unit B, Boston", "182", 182, 182, "LONDON ST", None, "BOSTON"),
        ("181-183 State St", "181-183", 181, 183, "STATE ST", None, None),
        ("181 - 183 State St", "181-183", 181, 183, "STATE ST", None, None),
        ("12A Elm St", "12A", 12, 12, "ELM ST", None, None),
        ("26 Clayton St Dorchester MA 02122", "26", 26, 26, "CLAYTON ST", "02122", "DORCHESTER"),
        ("516 E Broadway 3, 02127", "516", 516, 516, "E BROADWAY", "02127", None),
        ("352 Riverway 352-1", "352", 352, 352, "RIVERWAY", None, None),
        ("37 Branch St Bsmt, 02108", "37", 37, 37, "BRANCH ST", "02108", None),
    ],
)
def test_parse_address(raw, number, lo, hi, street, zip_, place):
    p = parse_address(raw)
    assert (p.number, p.number_from, p.number_to, p.street, p.zip, p.place) == (
        number, lo, hi, street, zip_, place,
    )


@pytest.mark.parametrize("raw", ["", "London St", "   ", "Apartment near campus"])
def test_parse_address_without_number(raw):
    assert parse_address(raw) is None


# --- Rental rule --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "lu, own_occ, units, rental_units, expected",
    [
        ("R3", "Y", 3, 0, True),  # owner lives in one unit, rents the others
        ("R2", "N", 2, 0, True),
        ("A", "N", 12, 0, True),
        ("R1", "Y", 1, 0, False),
        ("R1", "N", 1, 0, True),
        ("CD", "N", 1, 0, True),
        ("CD", "Y", 1, 0, False),
        ("CM", None, 3, 1, True),
        ("CM", None, 3, 0, False),
        ("CM", None, 0, 0, False),
        ("C", "N", 0, 0, False),
        ("E", "N", 0, 0, False),
    ],
)
def test_rental_rule(lu, own_occ, units, rental_units, expected):
    assert classify(lu, own_occ, units, rental_units)[0] is expected


# --- Preprocessing ------------------------------------------------------------------------

def test_no_owner_or_mailing_data_in_db(db):
    with sqlite3.connect(db) as con:
        for table in ("addresses", "properties"):
            cols = {r[1].upper() for r in con.execute(f"PRAGMA table_info({table})")}
            # owner_occupied is a Y/N flag, not a name; everything else owner/mail-related is PII.
            assert not {c for c in cols if ("OWNER" in c or "MAIL" in c) and c != "OWNER_OCCUPIED"}, cols
            for row in con.execute(f"SELECT * FROM {table}"):
                text = " ".join(str(v) for v in row).upper()
                assert not any(w in text for w in ("SECRET", "TEST OWNER"))


def test_addresses_are_building_level(db):
    with sqlite3.connect(db) as con:
        n = con.execute("SELECT COUNT(*) FROM addresses WHERE street_key='LONDON ST'").fetchone()[0]
    assert n == 1  # the "#2" unit row is dropped


def test_condo_units_roll_up(db):
    m = lookup("217 Lexington St 02128", db)
    assert m.building.land_use == "CM"
    assert m.building.units == 2
    assert m.building.is_rental  # one of two units isn't owner-occupied
    assert m.building.year_remodeled == 2020
    assert m.building.heat_type == "F - Forced Hot Air"


def test_meta_snapshot(db):
    with sqlite3.connect(db) as con:
        assert dict(con.execute("SELECT key, value FROM meta"))["snapshot_date"] == "2026-10-24"


# --- Lookup -------------------------------------------------------------------------------

def test_exact_match_rental(db):
    m = lookup("182 London St Apt 2, East Boston, MA 02128", db)
    assert m.matched and m.match_type == "exact"
    assert (m.sam_id, m.parcel_id, m.ward, m.zip) == ("1", "0106069000", 1, "02128")
    assert m.is_rental and m.building.units == 3 and m.building.year_built == 1910


def test_number_inside_range(db):
    m = lookup("182 State St, Boston 02109", db)
    assert m.matched and m.match_type == "range"
    assert m.display_address == "181-183 State St"
    assert not m.is_rental


def test_missing_suffix(db):
    m = lookup("182 london", db)
    assert m.matched and m.match_type == "no_suffix"


def test_owner_occupied_single_family_not_rental(db):
    m = lookup("10 Oak Ave 02122", db)
    assert m.matched and not m.is_rental
    assert m.building.rental_reason == "owner-occupied single unit"


def test_ambiguous_street_needs_zip(db):
    m = lookup("10 Oak Ave", db)
    assert not m.matched and m.reason == "ambiguous"
    assert m.candidates == ("02122", "02131")
    # Neighborhood resolves it.
    m = lookup("10 Oak Ave, Roslindale", db)
    assert m.matched and m.zip == "02131" and m.is_rental


def test_mount_vs_mt(db):
    assert lookup("9 Mt Vernon St, Boston", db).matched


@pytest.mark.parametrize(
    "raw, reason",
    [
        ("London St", "no_number"),
        ("12 Example St, Amherst, MA 01002", "outside_boston"),
        ("12 Example St, Amherst", "outside_boston"),
        ("999 London St 02128", "not_found"),
        ("5 Nowhere Rd", "not_found"),
    ],
)
def test_unmatched_returns_reason_not_error(db, raw, reason):
    m = lookup(raw, db)
    assert not m.matched and m.reason == reason
    assert m.reason_text


def test_missing_database(tmp_path):
    m = lookup("182 London St", tmp_path / "nope.sqlite")
    assert not m.matched and m.reason == "data_unavailable"
