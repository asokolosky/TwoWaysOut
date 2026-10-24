"""Ranking service: tenant decay, official score, privacy separation of simulated reports."""

import shutil
import sqlite3
from dataclasses import fields
from datetime import date, timedelta

import pytest

from app.content.report_categories import REPORT_CATEGORIES
from app.services import ranking
from app.services.ranking import (
    HALF_LIFE_DAYS,
    OFFICIAL_CAP,
    SimulatedBuilding,
    building_reports,
    rank_real_buildings,
    rank_simulated,
)
from tests.fixtures.boston_db import SNAPSHOT, build_fixture_db

AS_OF = date(2026, 10, 24)
LONDON = "0106069000"  # rental; 1 open egress violation + 3 records in the last 12 months
LEXINGTON = "0100010000"  # rental condo building; 1 recent record
OAK_DORCHESTER = "1500001000"  # owner-occupied single family: not a rental
LONDON_OFFICIAL = 3 * 1 + 3


@pytest.fixture(scope="module")
def boston_db(tmp_path_factory):
    return build_fixture_db(tmp_path_factory.mktemp("boston") / "boston.sqlite")


@pytest.fixture
def boston_copy(boston_db, tmp_path):
    path = tmp_path / "boston_copy.sqlite"
    shutil.copy(boston_db, path)
    return path


@pytest.fixture
def no_boston(tmp_path):
    return tmp_path / "missing.sqlite"


def add_report(app_db, *, key, category="other", observed=None, created="2026-10-24", parcel=None,
               address=None, zip_code=None, ward=None, simulated=0, description=None):
    with sqlite3.connect(app_db) as con:
        con.execute(
            """INSERT INTO reports (address_input, address_key, parcel_id, ward, zip, category,
                                    description, observed_date, created_at, is_simulated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (address or key.title(), key, parcel, ward, zip_code, category, description, observed, created, simulated),
        )


def add_parcel_report(app_db, parcel, **kw):
    add_report(app_db, key=f"PARCEL {parcel}", parcel=parcel, **kw)


def add_simulated(app_db, n=40):
    cats = list(REPORT_CATEGORIES)
    with sqlite3.connect(app_db) as con:
        for i in range(n):
            con.execute(
                """INSERT INTO simulated_reports (sim_building, ward, rental_type, category, description,
                                                  observed_date, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (f"SIM-{i % 8:02d}", 21, "3-family", cats[i % len(cats)], "Fictional", "2026-10-01", "2026-10-02"),
            )


def by_key(rows):
    return {b.building_key: b for b in rows}


def tenant_only(app_db, no_boston, **kw):
    return by_key(rank_real_buildings(app_db, no_boston, as_of=AS_OF, **kw))


# --- Tenant score -------------------------------------------------------------------------


def test_severity_weights(app_db, no_boston):
    expected = {"no_second_exit": 5, "smoke_alarm": 5, "blocked_exit": 4, "electrical_hazard": 4,
                "heating_hazard": 3, "other": 1}
    for cat in expected:
        add_report(app_db, key=f"1 {cat} ST 02134", category=cat, created=AS_OF.isoformat())
    rows = tenant_only(app_db, no_boston)
    for cat, sev in expected.items():
        assert rows[f"1 {cat} ST 02134"].tenant_score == pytest.approx(sev)


@pytest.mark.parametrize(
    "days_ago,factor",
    [(0, 1.0), (HALF_LIFE_DAYS, 0.5), (2 * HALF_LIFE_DAYS, 0.25), (-30, 1.0)],
)
def test_decay_is_exact(app_db, no_boston, days_ago, factor):
    observed = (AS_OF - timedelta(days=days_ago)).isoformat()
    add_report(app_db, key="1 DECAY ST 02134", category="smoke_alarm", observed=observed, created="2026-10-24")
    b = tenant_only(app_db, no_boston)["1 DECAY ST 02134"]
    assert b.tenant_score == pytest.approx(5 * factor, abs=1e-12)


def test_created_at_used_when_no_observed_date(app_db, no_boston):
    add_report(app_db, key="1 OLD ST 02134", category="other", created=(AS_OF - timedelta(days=90)).isoformat())
    assert tenant_only(app_db, no_boston)["1 OLD ST 02134"].tenant_score == pytest.approx(0.5)


def test_reports_sum_per_building(app_db, no_boston):
    add_report(app_db, key="1 SUM ST 02134", category="smoke_alarm")
    add_report(app_db, key="1 SUM ST 02134", category="heating_hazard")
    b = tenant_only(app_db, no_boston)["1 SUM ST 02134"]
    assert b.report_count == 2
    assert b.tenant_score == pytest.approx(8)
    assert b.top_hazards == (REPORT_CATEGORIES["smoke_alarm"].label, REPORT_CATEGORIES["heating_hazard"].label)


def test_simulated_flag_rows_in_reports_ignored(app_db, no_boston):
    add_report(app_db, key="1 REAL ST 02134", category="other")
    add_report(app_db, key="1 REAL ST 02134", category="smoke_alarm", simulated=1)
    add_report(app_db, key="1 FAKE ST 02134", category="smoke_alarm", simulated=1)
    rows = tenant_only(app_db, no_boston)
    assert set(rows) == {"1 REAL ST 02134"}
    assert rows["1 REAL ST 02134"].tenant_score == pytest.approx(1)
    assert rows["1 REAL ST 02134"].report_count == 1


# --- Official score -----------------------------------------------------------------------


def test_official_formula_for_rental(app_db, boston_db):
    b = by_key(rank_real_buildings(app_db, boston_db, as_of=AS_OF))[f"PARCEL {LONDON}"]
    assert b.open_violations == 1
    assert b.recent_official_records == 3  # 2026-09-01, 2026-02-01, 2026-01-15; not 2025-05-01 or 2024
    assert b.official_score == LONDON_OFFICIAL
    assert b.tenant_score == 0
    assert b.report_count == 0
    assert b.is_boston_rental
    assert b.rental_type_label == "THREE-FAM DWELLING"
    assert b.display_address == "182 London St, East Boston 02128"
    assert b.zip == "02128"
    assert b.top_hazards[0] == "Exits and ways out"  # 3 (open) + 1 (recent)


def test_official_only_buildings_appear(app_db, boston_db):
    rows = by_key(rank_real_buildings(app_db, boston_db, as_of=AS_OF))
    assert set(rows) == {f"PARCEL {LONDON}", f"PARCEL {LEXINGTON}"}
    assert rows[f"PARCEL {LEXINGTON}"].official_score == 1


def test_official_cap(app_db, boston_copy):
    with sqlite3.connect(boston_copy) as con:
        for i in range(5):
            con.execute(
                "INSERT INTO records (parcel_id, date, source, kind, category, description, status) "
                "VALUES (?, ?, 'isd_violations', 'violation', 'electrical', 'Electrical', 'Open')",
                (LONDON, f"2026-0{i + 3}-01"),
            )
    b = by_key(rank_real_buildings(app_db, boston_copy, as_of=AS_OF))[f"PARCEL {LONDON}"]
    assert b.open_violations == 6
    assert b.recent_official_records == 8
    assert 3 * 6 + 8 > OFFICIAL_CAP
    assert b.official_score == OFFICIAL_CAP


def test_total_is_sum_of_parts(app_db, boston_db):
    add_parcel_report(app_db, LONDON, category="blocked_exit", observed="2026-07-26")  # 90 days before
    b = by_key(rank_real_buildings(app_db, boston_db, as_of=AS_OF))[f"PARCEL {LONDON}"]
    assert b.tenant_score == pytest.approx(2.0)
    assert b.official_score == LONDON_OFFICIAL
    assert b.total_score == pytest.approx(b.tenant_score + b.official_score)
    assert b.report_count == 1


def test_outside_boston_text_key(app_db, boston_db):
    add_report(app_db, key="12 EXAMPLE ST 01002", category="smoke_alarm", address="12 Example St, Amherst 01002",
               zip_code="01002")
    b = by_key(rank_real_buildings(app_db, boston_db, as_of=AS_OF))["12 EXAMPLE ST 01002"]
    assert b.official_score == 0
    assert b.parcel_id is None
    assert not b.is_boston_rental
    assert b.display_address == "12 Example St 01002"
    assert b.zip == "01002"
    assert b.tenant_score == pytest.approx(5)


def test_non_rental_parcel_has_no_official_history(app_db, boston_copy):
    # Even if records existed for a non-rental parcel, they must not be used.
    with sqlite3.connect(boston_copy) as con:
        con.execute(
            "INSERT INTO records (parcel_id, date, source, kind, category, description, status) "
            "VALUES (?, '2026-09-01', 'isd_violations', 'violation', 'egress', 'Egress', 'Open')",
            (OAK_DORCHESTER,),
        )
    rows = by_key(rank_real_buildings(app_db, boston_copy, as_of=AS_OF))
    assert f"PARCEL {OAK_DORCHESTER}" not in rows

    add_parcel_report(app_db, OAK_DORCHESTER, category="heating_hazard")
    b = by_key(rank_real_buildings(app_db, boston_copy, as_of=AS_OF))[f"PARCEL {OAK_DORCHESTER}"]
    assert b.official_score == 0
    assert b.open_violations == 0 and b.recent_official_records == 0
    assert not b.is_boston_rental
    assert b.rental_type_label is None
    assert b.top_hazards == (REPORT_CATEGORIES["heating_hazard"].label,)
    assert b.tenant_score == pytest.approx(3)


def test_missing_boston_db_still_ranks_tenant_reports(app_db, no_boston):
    add_parcel_report(app_db, LONDON, category="smoke_alarm", address="182 London St 02128")
    [b] = rank_real_buildings(app_db, no_boston, as_of=AS_OF)
    assert b.official_score == 0
    assert b.display_address == "182 London St 02128"


def test_boston_db_without_history(app_db, tmp_path):
    bare = build_fixture_db(tmp_path / "bare.sqlite", with_history=False)
    add_parcel_report(app_db, LONDON, category="smoke_alarm")
    [b] = rank_real_buildings(app_db, bare, as_of=AS_OF)
    assert b.official_score == 0
    assert b.display_address == "182 London St, East Boston 02128"


def test_year_built_does_not_change_scores(app_db, boston_db, boston_copy):
    add_parcel_report(app_db, LONDON, category="electrical_hazard", observed="2026-09-01")
    before = rank_real_buildings(app_db, boston_db, as_of=AS_OF)
    with sqlite3.connect(boston_copy) as con:
        con.execute("UPDATE properties SET year_built = 2025")
    after = rank_real_buildings(app_db, boston_copy, as_of=AS_OF)
    assert before == after


def test_zip_and_neighborhood_do_not_change_scores(app_db, boston_db, boston_copy):
    add_parcel_report(app_db, LONDON, category="electrical_hazard", observed="2026-09-01")
    with sqlite3.connect(boston_copy) as con:
        con.execute("UPDATE addresses SET zip = '02199', neighborhood = 'Back Bay'")
    scores = lambda rows: {b.building_key: (b.tenant_score, b.official_score, b.total_score) for b in rows}  # noqa: E731
    assert scores(rank_real_buildings(app_db, boston_db, as_of=AS_OF)) == scores(
        rank_real_buildings(app_db, boston_copy, as_of=AS_OF)
    )


def test_snapshot_window_uses_boston_snapshot_not_as_of(app_db, boston_db):
    later = rank_real_buildings(app_db, boston_db, as_of=date(2027, 6, 1))
    assert by_key(later)[f"PARCEL {LONDON}"].official_score == LONDON_OFFICIAL
    assert SNAPSHOT == "2026-10-24"


# --- Simulated separation -----------------------------------------------------------------


def test_real_ranking_identical_with_simulated_rows(app_db, boston_db):
    add_parcel_report(app_db, LONDON, category="smoke_alarm")
    add_report(app_db, key="12 EXAMPLE ST 01002", category="other")
    before = rank_real_buildings(app_db, boston_db, as_of=AS_OF)
    add_simulated(app_db, 40)
    after = rank_real_buildings(app_db, boston_db, as_of=AS_OF)
    assert before == after
    assert all("SIM" not in b.building_key for b in after)


def test_rank_simulated_is_masked(app_db):
    add_simulated(app_db, 40)
    add_report(app_db, key="12 EXAMPLE ST 01002", category="smoke_alarm")  # real, must not appear
    sims = rank_simulated(app_db, as_of=AS_OF)
    assert len(sims) == 8
    assert sum(s.report_count for s in sims) == 40
    names = {f.name for f in fields(SimulatedBuilding)}
    for banned in ("address", "display_address", "address_input", "address_key", "parcel_id", "sam_id", "zip"):
        assert banned not in names
        assert not hasattr(sims[0], banned)
    for s in sims:
        assert s.is_simulated is True
        assert "Simulated" in s.label
        assert s.label == "Simulated report · Ward 21 · 3-family"
    assert [s.rank for s in sims] == list(range(1, 9))
    scores = [s.tenant_score for s in sims]
    assert scores == sorted(scores, reverse=True)


def test_rank_simulated_uses_same_formula(app_db):
    with sqlite3.connect(app_db) as con:
        con.execute(
            "INSERT INTO simulated_reports (sim_building, ward, rental_type, category, observed_date, created_at) "
            "VALUES ('SIM-01', 5, '2-family', 'smoke_alarm', ?, '2026-10-24')",
            ((AS_OF - timedelta(days=90)).isoformat(),),
        )
    [s] = rank_simulated(app_db, as_of=AS_OF)
    assert s.tenant_score == pytest.approx(2.5)


# --- Ordering, filters, limit -------------------------------------------------------------


def test_tie_breaking(app_db, no_boston):
    # Same total: higher tenant first is covered below; here tenant ties too.
    add_report(app_db, key="2 B ST", category="other", created="2026-10-24")
    add_report(app_db, key="1 A ST", category="other", created="2026-10-24")
    # Same score (observed date drives decay) but more recent activity wins.
    add_report(app_db, key="3 C ST", category="other", observed="2026-10-24", created="2026-10-24")
    rows = rank_real_buildings(app_db, no_boston, as_of=AS_OF)
    assert [b.display_address for b in rows] == ["1 A St", "2 B St", "3 C St"]

    add_report(app_db, key="0 D ST", category="other", observed="2026-10-20", created="2026-10-25")
    add_report(app_db, key="0 D ST", category="other", observed="2026-10-24", created="2026-10-24")
    rows = rank_real_buildings(app_db, no_boston, as_of=date(2026, 10, 20))
    assert rows[0].display_address == "0 D St"
    assert [b.rank for b in rows] == [1, 2, 3, 4]


def test_latest_activity_breaks_tie(app_db, no_boston):
    add_report(app_db, key="1 OLD ST", category="other", observed="2026-10-30", created="2026-10-24")
    add_report(app_db, key="9 NEW ST", category="other", observed="2026-10-30", created="2026-11-02")
    rows = rank_real_buildings(app_db, no_boston, as_of=AS_OF)  # both future-dated: full weight
    assert rows[0].tenant_score == rows[1].tenant_score
    assert [b.display_address for b in rows] == ["9 New St", "1 Old St"]


def test_tenant_breaks_total_tie(app_db, boston_db):
    # Lexington has official 1; a text-key building with a fresh "other" report has tenant 1.
    add_report(app_db, key="Z", address="Z St", category="other", created="2026-01-01", observed="2026-10-24")
    rows = rank_real_buildings(app_db, boston_db, as_of=AS_OF)
    lex = [b for b in rows if b.total_score == pytest.approx(1)]
    assert [b.building_key for b in lex] == ["Z", f"PARCEL {LEXINGTON}"]


def test_zip_filter(app_db, boston_db):
    add_report(app_db, key="12 EXAMPLE ST 01002", category="other", zip_code="01002")
    rows = rank_real_buildings(app_db, boston_db, as_of=AS_OF, zip_code="02128")
    assert {b.building_key for b in rows} == {f"PARCEL {LONDON}", f"PARCEL {LEXINGTON}"}
    assert [b.rank for b in rows] == [1, 2]
    rows = rank_real_buildings(app_db, boston_db, as_of=AS_OF, zip_code="01002")
    assert [b.building_key for b in rows] == ["12 EXAMPLE ST 01002"]
    assert rows[0].rank == 1


def test_category_filter(app_db, boston_db):
    add_report(app_db, key="12 EXAMPLE ST 01002", category="blocked_exit")
    add_report(app_db, key="14 EXAMPLE ST 01002", category="heating_hazard")
    by_id = rank_real_buildings(app_db, boston_db, as_of=AS_OF, category="blocked_exit")
    assert [b.building_key for b in by_id] == ["12 EXAMPLE ST 01002"]
    assert by_id[0].rank == 1
    # A fire category matches linked tenant reports and official records.
    egress = rank_real_buildings(app_db, boston_db, as_of=AS_OF, category="egress")
    assert {b.building_key for b in egress} == {"12 EXAMPLE ST 01002", f"PARCEL {LONDON}"}
    smoke = rank_real_buildings(app_db, boston_db, as_of=AS_OF, category="smoke_alarms")
    assert {b.building_key for b in smoke} == {f"PARCEL {LONDON}", f"PARCEL {LEXINGTON}"}


def test_limit(app_db, boston_db):
    for i in range(5):
        add_report(app_db, key=f"{i} LIMIT ST 01002", category="other")
    full = rank_real_buildings(app_db, boston_db, as_of=AS_OF)
    assert len(full) == 7
    top = rank_real_buildings(app_db, boston_db, as_of=AS_OF, limit=3)
    assert top == full[:3]
    assert top[0].building_key == f"PARCEL {LONDON}"


def test_empty_databases(tmp_path, no_boston):
    assert rank_real_buildings(tmp_path / "none.sqlite", no_boston) == []
    assert rank_simulated(tmp_path / "none.sqlite") == []
    assert building_reports(tmp_path / "none.sqlite", "X") == []


# --- Building detail ----------------------------------------------------------------------


def test_building_reports_real_only(app_db):
    add_parcel_report(app_db, LONDON, category="smoke_alarm", observed="2026-09-01", description="Alarm missing")
    add_parcel_report(app_db, LONDON, category="heating_hazard", observed="2026-10-01")
    add_parcel_report(app_db, LONDON, category="other", simulated=1)
    add_simulated(app_db, 5)
    rows = building_reports(app_db, f"PARCEL {LONDON}")
    assert [r.category for r in rows] == ["heating_hazard", "smoke_alarm"]
    assert rows[1].category_label == REPORT_CATEGORIES["smoke_alarm"].label
    assert rows[1].description == "Alarm missing"
    assert rows[1].status == "open"
    assert rows[1].created_at == "2026-10-24"


def test_scoring_ignores_age_and_area_by_design():
    # Guard against building age creeping in as a score input: the module never reads it.
    src = open(ranking.__file__).read()
    assert "year_built" not in src
    assert "year_remodeled" not in src


# --- Privacy: typed addresses, keys, dates, read-only access ------------------------------

UNIT_ADDRESS = "12 Example St Apt 3R, Amherst 01002"


def add_raw(app_db, *, address, key=None, parcel=None, category="other", created="2026-10-24",
            observed=None, zip_code=None):
    """Insert a report row directly, allowing a NULL address_key and arbitrary created_at."""
    with sqlite3.connect(app_db) as con:
        cur = con.execute(
            """INSERT INTO reports (address_input, address_key, parcel_id, zip, category, observed_date,
                                    created_at, is_simulated)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (address, key, parcel, zip_code, category, observed, created),
        )
        return cur.lastrowid


def all_text(b) -> str:
    return " | ".join(str(getattr(b, f.name)) for f in fields(b))


@pytest.mark.parametrize(
    "key,expected",
    [
        ("12 EXAMPLE ST 01002", "12 Example St 01002"),
        ("181-183 E BROADWAY 02127", "181-183 E Broadway 02127"),
        ("12A MT VERNON ST AMHERST", "12A Mt Vernon St Amherst"),
        ("5 COMMONWEALTH AVE N 02134", "5 Commonwealth Ave N 02134"),
        ("9 OCONNOR WAY NE 02120", "9 Oconnor Way NE 02120"),
        ("", ""),
    ],
)
def test_display_from_key(key, expected):
    from app.services.address_normalize import display_from_key

    assert display_from_key(key) == expected


def test_raw_address_input_never_displayed(app_db, boston_db):
    add_report(app_db, key="12 EXAMPLE ST 01002", address=UNIT_ADDRESS, category="smoke_alarm", zip_code="01002")
    add_raw(app_db, address="14 Example St Apt 3R, Amherst 01002")  # NULL key, derived at read time
    rows = by_key(rank_real_buildings(app_db, boston_db, as_of=AS_OF))
    assert rows["12 EXAMPLE ST 01002"].display_address == "12 Example St 01002"
    assert rows["14 EXAMPLE ST 01002"].display_address == "14 Example St 01002"
    for b in rows.values():
        text = all_text(b)
        assert "Apt" not in text and "3R" not in text and "APT" not in text
        assert not b.display_address.startswith("PARCEL")


def test_null_key_groups_with_normalized_key(app_db, no_boston):
    add_report(app_db, key="12 EXAMPLE ST 01002", address="12 Example St, Amherst 01002", category="other")
    add_raw(app_db, address=UNIT_ADDRESS, category="smoke_alarm")
    rows = tenant_only(app_db, no_boston)
    assert set(rows) == {"12 EXAMPLE ST 01002"}
    assert rows["12 EXAMPLE ST 01002"].report_count == 2
    # Same day, so newest id first.
    assert [r.category for r in building_reports(app_db, "12 EXAMPLE ST 01002")] == ["smoke_alarm", "other"]


def test_unparsable_null_key_is_opaque(app_db, no_boston):
    rid = add_raw(app_db, address="behind the blue house, ask for Jane", category="blocked_exit")
    [b] = rank_real_buildings(app_db, no_boston, as_of=AS_OF)
    assert b.building_key == f"UNKEYED {rid}"
    assert b.display_address == ranking.UNRECOGNIZED_ADDRESS == "Address not recognized"
    assert "Jane" not in all_text(b) and "blue" not in all_text(b)
    [r] = building_reports(app_db, f"UNKEYED {rid}")
    assert r.category == "blocked_exit"
    # Each unparsable report stays in its own group.
    rid2 = add_raw(app_db, address="same place as before", category="other")
    assert {b.building_key for b in rank_real_buildings(app_db, no_boston, as_of=AS_OF)} == {
        f"UNKEYED {rid}", f"UNKEYED {rid2}"}


def test_no_raw_text_key_sql_remains():
    src = open(ranking.__file__).read()
    assert "'ADDRESS '" not in src and "UPPER(TRIM(address_input))" not in src


def test_timestamp_dates_read_at_day_precision(app_db, no_boston):
    add_raw(app_db, address="1 Clock St 02134", key="1 CLOCK ST 02134", category="smoke_alarm",
            created="2026-07-26 13:45:10", observed=None)
    [b] = rank_real_buildings(app_db, no_boston, as_of=AS_OF)
    assert b.tenant_score == pytest.approx(2.5)  # 90 days before AS_OF
    assert b.latest_activity == "2026-07-26"
    [r] = building_reports(app_db, "1 CLOCK ST 02134")
    assert r.created_at == "2026-07-26"
    assert len(r.created_at) == 10
    assert r.created_month == "2026-07"
    assert r.observed_date is None and r.observed_month is None


def test_building_report_month_fields(app_db):
    add_parcel_report(app_db, LONDON, category="smoke_alarm", observed="2026-09-01", created="2026-10-02")
    [r] = building_reports(app_db, f"PARCEL {LONDON}")
    assert (r.observed_date, r.observed_month) == ("2026-09-01", "2026-09")
    assert (r.created_at, r.created_month) == ("2026-10-02", "2026-10")


def test_building_reports_works_on_read_only_file(app_db, tmp_path):
    import os
    import stat

    add_parcel_report(app_db, LONDON, category="smoke_alarm")
    ro = tmp_path / "readonly.sqlite"
    shutil.copy(app_db, ro)
    os.chmod(ro, 0o444)
    try:
        [r] = building_reports(ro, f"PARCEL {LONDON}")
        assert r.category == "smoke_alarm"
        assert stat.S_IMODE(os.stat(ro).st_mode) == 0o444
    finally:
        os.chmod(ro, 0o644)


def test_building_reports_does_not_open_read_write(app_db, monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("read-write connect used")

    monkeypatch.setattr("app.db.connect", boom)
    assert not hasattr(ranking, "connect")
    add_parcel_report(app_db, LONDON, category="other")
    assert len(building_reports(app_db, f"PARCEL {LONDON}")) == 1


def test_non_rental_parcel_hides_parcel_and_city_address(app_db, boston_db):
    add_parcel_report(app_db, OAK_DORCHESTER, category="heating_hazard",
                      address="10 Oak St Apt 2, Dorchester 02124", zip_code="02124")
    b = by_key(rank_real_buildings(app_db, boston_db, as_of=AS_OF))[f"PARCEL {OAK_DORCHESTER}"]
    assert b.parcel_id is None
    assert not b.is_boston_rental
    assert b.official_score == 0
    assert b.display_address == "10 Oak St 02124"
    assert "Apt" not in all_text(b)


def test_rental_parcel_keeps_parcel_and_city_address(app_db, boston_db):
    add_parcel_report(app_db, LONDON, category="other", address="182 London St Apt 3R 02128")
    b = by_key(rank_real_buildings(app_db, boston_db, as_of=AS_OF))[f"PARCEL {LONDON}"]
    assert b.parcel_id == LONDON
    assert b.display_address == "182 London St, East Boston 02128"
    assert "3R" not in all_text(b)


def test_rank_script_prints_building_level_addresses(app_db, no_boston, monkeypatch, capsys):
    import sys

    from app.config import Settings
    from scripts import rank

    add_report(app_db, key="12 EXAMPLE ST 01002", address=UNIT_ADDRESS, category="smoke_alarm")
    add_raw(app_db, address="14 Example St Apt 3R, Amherst 01002")
    add_raw(app_db, address="behind the blue house, ask for Jane")
    monkeypatch.setattr(rank, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(rank, "db_path", lambda settings: app_db)
    monkeypatch.setattr(rank, "DEFAULT_DB", no_boston)
    monkeypatch.setattr(sys, "argv", ["rank"])
    rank.main()
    out = capsys.readouterr().out
    assert "12 Example St 01002" in out
    assert "14 Example St 01002" in out
    assert "Address not recognized" in out
    for banned in ("Apt", "3R", "Jane", "blue house", "Amherst"):
        assert banned not in out
