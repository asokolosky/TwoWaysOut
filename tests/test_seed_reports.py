"""scripts/seed_reports.py: simulated tenant reports for the dashboard demo.

Uses a tmp app DB and the fixture Boston DB; never touches data/app.sqlite or data/boston.sqlite.
"""

import re
import sqlite3
from collections import Counter
from datetime import date, timedelta

import pytest

from app.content.report_categories import REPORT_CATEGORIES
from app.db import connect
from app.services.reports import redact_contact_info
from scripts import seed_reports
from tests.fixtures.boston_db import build_fixture_db

TODAY = date(2026, 10, 24)
STREET_RE = re.compile(r"\d+\s+\w+\s+(St|Ave|Rd|Street|Avenue)\b", re.IGNORECASE)
SIM_COLUMNS = "sim_building, ward, rental_type, category, description, observed_date, created_at"


@pytest.fixture(scope="module")
def boston_db(tmp_path_factory):
    return build_fixture_db(tmp_path_factory.mktemp("boston") / "boston.sqlite")


@pytest.fixture(params=["fixture", "missing"])
def boston(request, boston_db, tmp_path):
    return boston_db if request.param == "fixture" else tmp_path / "does-not-exist.sqlite"


def _rows(path):
    con = connect(path)
    try:
        return [tuple(r) for r in con.execute(f"SELECT {SIM_COLUMNS} FROM simulated_reports ORDER BY id")]
    finally:
        con.close()


def test_counts_and_ids(app_db, boston):
    s = seed_reports.seed(app_db, boston, today=TODAY)
    rows = _rows(app_db)
    assert s["rows"] == len(rows) == sum(seed_reports.REPORTS_PER_BUILDING) == 40
    ids = {r[0] for r in rows}
    assert ids == {f"SIM-{i:02d}" for i in range(1, 15)}
    per_building = {b: sum(1 for r in rows if r[0] == b) for b in ids}
    assert all(1 <= n <= 6 for n in per_building.values())
    # Each SIM building has one consistent ward and rental type.
    for b in ids:
        assert len({(r[1], r[2]) for r in rows if r[0] == b}) == 1
    assert all(r[2] in seed_reports.RENTAL_TYPES.values() for r in rows)
    assert all(isinstance(r[1], int) and r[1] > 0 for r in rows)


def test_fallback_source_when_boston_missing(app_db, tmp_path):
    s = seed_reports.seed(app_db, tmp_path / "nope.sqlite", today=TODAY)
    assert "fallback" in s["source"]
    fallback = {(w, t) for w, t, _ in seed_reports.FALLBACK_COMBOS}
    assert {(r[1], r[2]) for r in _rows(app_db)} <= fallback


def _real_group_sizes(path):
    con = sqlite3.connect(path)
    sizes = Counter(
        (int(pid[:2]), seed_reports.RENTAL_TYPES[lu])
        for pid, lu in con.execute("SELECT parcel_id, land_use FROM properties WHERE is_rental = 1")
        if pid and lu in seed_reports.RENTAL_TYPES
    )
    con.close()
    return sizes


def _grouped_boston_db(path, groups):
    """Minimal boston.sqlite with only a properties table: {(ward, land_use): n_rentals}."""
    con = sqlite3.connect(path)
    with con:
        con.execute("CREATE TABLE properties (parcel_id TEXT, land_use TEXT, is_rental INTEGER)")
        rows = []
        for (ward, lu), n in groups.items():
            rows += [(f"{ward:02d}{lu}{i:06d}", lu, 1) for i in range(n)]
            rows.append((f"{ward:02d}{lu}999999", lu, 0))  # a non-rental never counts
        con.executemany("INSERT INTO properties VALUES (?, ?, ?)", rows)
    con.close()
    return path


def test_uses_boston_aggregates(boston_db):
    combos, source = seed_reports.load_combos(boston_db)
    sizes = _real_group_sizes(boston_db)
    assert sizes
    # Tiny fixture DB: every real group is below the threshold, so none is used and the
    # synthetic fallback fills in, minus any pair matching a small real group.
    assert all(n < seed_reports.MIN_GROUP_SIZE for n in sizes.values())
    assert "boston.sqlite" in source and "fallback" in source
    pairs = {(w, t) for w, t, _ in combos}
    assert not pairs & set(sizes)
    assert pairs <= {(w, t) for w, t, _ in seed_reports.FALLBACK_COMBOS}


def test_min_group_size_threshold(tmp_path):
    db = _grouped_boston_db(tmp_path / "boston.sqlite", {(21, "R3"): 25, (3, "R4"): 3})
    combos, source = seed_reports.load_combos(db)
    assert (21, "3-family", 25) in combos
    assert all((w, t) != (3, "4-6 family") for w, t, _ in combos)
    # Only one real group passes, so the fallback tops up, but never with the small real group.
    assert "fallback" in source
    assert [c for c in combos if c[2] == 25] == [(21, "3-family", 25)]


def test_seeded_groups_meet_min_size(tmp_path):
    groups = {(w, lu): 20 + 3 * i for i, (w, lu) in enumerate(
        [(21, "R3"), (21, "R2"), (22, "R3"), (22, "R2"), (10, "R3"), (10, "R4"), (4, "A"), (4, "CM"),
         (5, "CM"), (5, "A"), (3, "RC"), (3, "A"), (14, "R3"), (15, "R3"), (7, "R2"), (17, "R1")]
    )}
    groups.update({(3, "R4"): 2, (19, "R2"): 1, (9, "CD"): 19})
    db = _grouped_boston_db(tmp_path / "boston.sqlite", groups)
    combos, source = seed_reports.load_combos(db)
    assert source == "boston.sqlite aggregates"
    sizes = _real_group_sizes(db)
    assert all(sizes[(w, t)] == n >= seed_reports.MIN_GROUP_SIZE for w, t, n in combos)
    app = tmp_path / "app.sqlite"
    seed_reports.seed(app, db, today=TODAY)
    seeded = {(r[1], r[2]) for r in _rows(app)}
    assert len(seeded) == seed_reports.NUM_BUILDINGS
    assert all(sizes[k] >= seed_reports.MIN_GROUP_SIZE for k in seeded)


def test_deterministic_and_idempotent(tmp_path, boston):
    a, b = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    seed_reports.seed(a, boston, today=TODAY)
    seed_reports.seed(b, boston, today=TODAY)
    assert _rows(a) == _rows(b)
    first = _rows(a)
    seed_reports.seed(a, boston, today=TODAY)
    assert _rows(a) == first
    assert len(_rows(a)) == 40


def test_categories_and_dates(app_db, boston):
    seed_reports.seed(app_db, boston, today=TODAY)
    rows = _rows(app_db)
    cats = [r[3] for r in rows]
    assert set(cats) <= set(REPORT_CATEGORIES)
    top = {"smoke_alarm", "no_second_exit", "heating_hazard"}
    assert sum(c in top for c in cats) > len(cats) / 2
    earliest = TODAY - timedelta(days=seed_reports.DAYS_BACK)
    for r in rows:
        observed, created = date.fromisoformat(r[5]), date.fromisoformat(r[6])
        assert earliest <= observed <= TODAY
        assert observed <= created <= TODAY
        assert (created - observed).days <= seed_reports.MAX_CREATED_LAG_DAYS


def test_reports_table_untouched(app_db, boston):
    con = connect(app_db)
    with con:
        con.execute(
            "INSERT INTO reports (address_input, category, description, is_simulated) "
            "VALUES ('1 Example Ln', 'other', 'real report', 0)"
        )
    before = [tuple(r) for r in con.execute("SELECT * FROM reports")]
    con.close()
    seed_reports.seed(app_db, boston, today=TODAY)
    seed_reports.seed(app_db, boston, today=TODAY)
    con = connect(app_db)
    after = [tuple(r) for r in con.execute("SELECT * FROM reports")]
    con.close()
    assert after == before and len(after) == 1


def test_descriptions_are_generic(app_db, boston):
    seed_reports.seed(app_db, boston, today=TODAY)
    all_text = [d for ds in seed_reports.DESCRIPTIONS.values() for d in ds]
    all_text += [r[4] for r in _rows(app_db)]
    for d in all_text:
        cleaned, changed = redact_contact_info(d)
        assert not changed and cleaned == d
        assert not STREET_RE.search(d), d
        assert not re.search(r"@|\d{3}[-.\s]?\d{3}[-.\s]?\d{4}", d), d
        assert d.startswith("Simulated report:")


def test_simulated_table_has_no_location_columns(app_db, boston):
    seed_reports.seed(app_db, boston, today=TODAY)
    con = sqlite3.connect(app_db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(simulated_reports)")}
    con.close()
    assert not cols & {"address_input", "address_key", "display_address", "parcel_id", "sam_id", "zip"}


def test_cli_main(tmp_path, boston_db, capsys):
    db = tmp_path / "cli.sqlite"
    assert seed_reports.main(["--db", str(db), "--boston-db", str(boston_db)]) == 0
    out = capsys.readouterr().out
    assert "Seeded 40 simulated reports across 14 simulated buildings" in out
    assert "SIM-01: ward" in out and "Per category:" in out and "Observed dates:" in out
    assert len(_rows(db)) == 40
