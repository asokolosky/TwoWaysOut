"""Report form: several problem types can be selected in one submission."""

import sqlite3
from datetime import date

import pytest

from app.content.report_categories import REPORT_CATEGORIES
from app.db import init_db
from app.main import app
from app.services.boston import get_boston_db
from app.services.ranking import building_reports, rank_real_buildings
from app.services.reports import ReportError, order_categories, save_report
from tests.fixtures.boston_db import build_fixture_db

AS_OF = date.today()
LONDON_KEY = "PARCEL 0106069000"


@pytest.fixture(scope="module")
def boston_db(tmp_path_factory):
    return build_fixture_db(tmp_path_factory.mktemp("bos") / "boston.sqlite")


@pytest.fixture
def with_boston(client, boston_db):
    app.dependency_overrides[get_boston_db] = lambda: boston_db
    return client


def stored(app_db):
    with sqlite3.connect(app_db) as con:
        return con.execute("SELECT category, extra_categories FROM reports ORDER BY id").fetchall()


def test_form_uses_checkboxes(client):
    html = client.get("/report").text
    assert html.count('type="checkbox"') == len(REPORT_CATEGORIES)
    assert 'type="radio"' not in html
    assert "Check all that apply." in html
    assert 'aria-describedby="category-help"' in html


def test_multiple_problems_saved_most_serious_first(with_boston, app_db):
    resp = with_boston.post(
        "/report",
        data={"address": "182 London St 02128", "category": ["heating_hazard", "smoke_alarm", "other"]},
    )
    assert resp.status_code == 200
    assert stored(app_db) == [("smoke_alarm", "heating_hazard,other")]
    html = resp.text
    assert "Problems" in html
    # Listed most serious first.
    labels = [REPORT_CATEGORIES[c].label for c in ("smoke_alarm", "heating_hazard", "other")]
    positions = [html.index(lbl) for lbl in labels]
    assert positions == sorted(positions)


def test_single_problem_still_works(with_boston, app_db):
    resp = with_boston.post("/report", data={"address": "182 London St 02128", "category": "blocked_exit"})
    assert resp.status_code == 200
    assert stored(app_db) == [("blocked_exit", None)]
    assert ">Problem<" in resp.text


@pytest.mark.parametrize("cats", [[], ["aliens"], ["smoke_alarm", "aliens"]])
def test_invalid_or_missing_selection_rejected(with_boston, app_db, cats):
    resp = with_boston.post("/report", data={"address": "182 London St 02128", "category": cats})
    assert resp.status_code == 422
    assert "Choose what kind of problem" in resp.text
    assert stored(app_db) == []


def test_error_keeps_valid_boxes_checked(with_boston):
    html = with_boston.post(
        "/report", data={"address": "London St", "category": ["smoke_alarm", "blocked_exit"]}
    ).text
    assert 'value="smoke_alarm"\n                 checked' in html or 'value="smoke_alarm" checked' in " ".join(html.split())
    assert 'value="blocked_exit" checked' in " ".join(html.split())
    assert 'value="other" checked' not in " ".join(html.split())


def test_duplicates_collapsed():
    assert order_categories(["other", "smoke_alarm", "other"]) == ["smoke_alarm", "other"]
    with pytest.raises(ReportError):
        order_categories([])


def test_checking_every_box_does_not_inflate_score(app_db, boston_db, tmp_path):
    save_report(app_db, boston_db, address="182 London St 02128", category=list(REPORT_CATEGORIES))
    [b] = [b for b in rank_real_buildings(app_db, boston_db, as_of=AS_OF) if b.building_key == LONDON_KEY]
    # Scored once at the most serious problem (severity 5), not the sum of all six.
    assert b.tenant_score == pytest.approx(5)
    assert b.report_count == 1


def test_extra_problems_count_for_hazards_and_filters(app_db, boston_db):
    save_report(app_db, boston_db, address="12 Example St, Amherst 01002", category=["smoke_alarm", "electrical_hazard"])
    rows = rank_real_buildings(app_db, boston_db, as_of=AS_OF, category="electrical_hazard")
    assert [b.display_address for b in rows] == ["12 Example St 01002"]
    assert REPORT_CATEGORIES["electrical_hazard"].label in rows[0].top_hazards
    [r] = building_reports(app_db, rows[0].building_key)
    assert r.categories == ("smoke_alarm", "electrical_hazard")
    assert r.category_labels[0] == REPORT_CATEGORIES["smoke_alarm"].label


def test_old_database_without_column_is_migrated_and_still_ranks(tmp_path, boston_db):
    db = tmp_path / "old.sqlite"
    with sqlite3.connect(db) as con:
        con.execute(
            """CREATE TABLE reports (id INTEGER PRIMARY KEY, address_input TEXT NOT NULL, address_key TEXT,
               display_address TEXT, parcel_id TEXT, sam_id TEXT, ward INTEGER, zip TEXT,
               category TEXT NOT NULL, description TEXT, observed_date TEXT, created_at TEXT NOT NULL,
               is_simulated INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'open')"""
        )
        con.execute(
            "INSERT INTO reports (address_input, address_key, category, created_at) "
            "VALUES ('12 Example St 01002', '12 EXAMPLE ST 01002', 'other', ?)",
            (AS_OF.isoformat(),),
        )
    # Read-only ranking works before migration.
    assert any(b.building_key == "12 EXAMPLE ST 01002" for b in rank_real_buildings(db, boston_db, as_of=AS_OF))
    init_db(db)
    with sqlite3.connect(db) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(reports)")}
    assert "extra_categories" in cols
    init_db(db)  # idempotent


def test_too_many_values_rejected(with_boston, app_db):
    cats = list(REPORT_CATEGORIES) + ["other"] * 50
    resp = with_boston.post("/report", data={"address": "182 London St 02128", "category": cats})
    assert resp.status_code == 422
    assert "Choose what kind of problem" in resp.text
    assert stored(app_db) == []


def test_crafted_value_not_echoed(with_boston, app_db):
    evil = '"><script>alert(1)</script>'
    resp = with_boston.post("/report", data={"address": "182 London St 02128", "category": ["smoke_alarm", evil]})
    assert resp.status_code == 422
    assert "<script>alert(1)" not in resp.text and "alert(1)" not in resp.text
    assert stored(app_db) == []


def test_multiselect_never_touches_simulated(with_boston, app_db):
    with sqlite3.connect(app_db) as con:
        con.execute(
            "INSERT INTO simulated_reports (sim_building, ward, rental_type, category) VALUES ('SIM-01', 21, '3-family', 'other')"
        )
    with_boston.post("/report", data={"address": "182 London St 02128", "category": ["smoke_alarm", "other"]})
    with sqlite3.connect(app_db) as con:
        assert con.execute("SELECT COUNT(*) FROM simulated_reports").fetchone()[0] == 1
        assert con.execute("SELECT is_simulated FROM reports").fetchall() == [(0,)]
