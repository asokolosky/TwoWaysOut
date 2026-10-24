"""Data Commons area housing: build-time fetch (mocked HTTP), census_zip table, and the card."""

import io
import json
import re
import sqlite3
import urllib.error

import pytest

from app.main import app
from app.services.boston import context_for_address, get_boston_db
from app.services.census import census_context, census_for_zip, zip_for_report
from scripts import fetch_datacommons as fdc
from scripts.preprocess_boston import load_census
from tests.fixtures.boston_db import build_fixture_db
from tests.fixtures.listings import SPARSE

HX = {"HX-Request": "true"}
FAKE_KEY = "test-key-not-real-123"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    return build_fixture_db(tmp_path_factory.mktemp("census") / "boston.sqlite")


def _api_response(zips):
    """A /v2/observation response in the documented shape, with two facets per value."""
    by_var = {}
    for i, var in enumerate(fdc.VARIABLES.values()):
        by_var[var] = {
            "byEntity": {
                f"zip/{z}": {
                    "orderedFacets": [
                        {"facetId": "other", "observations": [{"date": "2019", "value": 1}]},
                        {"facetId": "acs", "observations": [{"date": "2024", "value": 1000 * (i + 1)}]},
                    ]
                }
                for z in zips
                if z != "01004"  # PO-box ZIP: no data
            }
        }
    return {
        "byVariable": by_var,
        "facets": {
            "acs": {"importName": "CensusACS5YearSurvey", "provenanceUrl": "https://www.census.gov/", "measurementMethod": "CensusACS5yrSurvey"},
            "other": {"importName": "SomethingElse", "provenanceUrl": "https://example.org/"},
        },
    }


class FakeOpener:
    def __init__(self, fail=None):
        self.requests = []
        self.fail = fail

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        if self.fail:
            raise self.fail
        body = json.loads(req.data)
        zips = [d.split("/", 1)[1] for d in body["entity"]["dcids"]]
        return io.BytesIO(json.dumps(_api_response(zips)).encode())


# --- Build-time fetch ---------------------------------------------------------------------

def test_verified_variable_dcids():
    assert fdc.VARIABLES == {
        "housing_units": "Count_HousingUnit",
        "built_before_1940": "Count_HousingUnit_Before1939DateBuilt",
        "renter_occupied": "Count_HousingUnit_RenterOccupied",
        "owner_occupied": "Count_HousingUnit_OwnerOccupied",
    }


def test_place_list_is_boston_zips_plus_amherst(db, tmp_path):
    zips = fdc.place_list(db, tmp_path)
    assert {"01002", "01003", "01004", "01059"} <= set(zips)
    assert {"02128", "02122", "02109"} <= set(zips)
    assert all(re.fullmatch(r"\d{5}", z) for z in zips)


def test_no_key_exits_zero_without_network(monkeypatch, tmp_path, capsys, db):
    monkeypatch.delenv("DATACOMMONS_API_KEY", raising=False)
    opener = FakeOpener()
    assert fdc.main(opener=opener, raw_dir=tmp_path, db_path=db) == 0
    assert opener.requests == []
    assert not (tmp_path / "datacommons.json").exists()
    assert "DATACOMMONS_API_KEY is not set" in capsys.readouterr().out


def test_fetch_writes_json_with_provenance(monkeypatch, tmp_path, capsys, db):
    monkeypatch.setenv("DATACOMMONS_API_KEY", FAKE_KEY)
    opener = FakeOpener()
    assert fdc.main(opener=opener, raw_dir=tmp_path, db_path=db) == 0
    req = opener.requests[0]
    # Key in a header only, never in the URL; POST to the v2 observation API.
    assert req.full_url == fdc.API_URL and FAKE_KEY not in req.full_url
    assert req.get_header("X-api-key") == FAKE_KEY
    body = json.loads(req.data)
    assert body["date"] == "LATEST" and set(body["variable"]["dcids"]) == set(fdc.VARIABLES.values())
    assert FAKE_KEY not in capsys.readouterr().out

    data = json.loads((tmp_path / "datacommons.json").read_text())
    assert FAKE_KEY not in json.dumps(data)
    assert data["fetched"] and "Data Commons" in data["source"]
    by_zip = {p["zip"]: p for p in data["places"]}
    assert "01004" not in by_zip
    p = by_zip["01002"]
    # The ACS facet is preferred over the other one.
    assert (p["housing_units"], p["built_before_1940"], p["renter_occupied"], p["owner_occupied"]) == (1000, 2000, 3000, 4000)
    assert p["dates"]["housing_units"] == "2024"
    assert p["provenance"]["housing_units"]["importName"] == "CensusACS5YearSurvey"


def test_http_error_returns_1_without_leaking_key(monkeypatch, tmp_path, capsys, db):
    monkeypatch.setenv("DATACOMMONS_API_KEY", FAKE_KEY)
    err = urllib.error.HTTPError(fdc.API_URL, 401, "Unauthorized", {}, None)
    assert fdc.main(opener=FakeOpener(fail=err), raw_dir=tmp_path, db_path=db) == 1
    out = capsys.readouterr()
    assert "HTTP 401" in out.err and FAKE_KEY not in out.out + out.err
    assert not (tmp_path / "datacommons.json").exists()


def test_build_script_runs_datacommons_only_with_key():
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "scripts" / "build_data.sh").read_text()
    guard = text.index('if [[ -n "${DATACOMMONS_API_KEY_FILE:-}"')
    assert 'elif [[ -n "${DATACOMMONS_API_KEY:-}" || -n "${DATA_COMMONS_API_KEY:-}" ]]' in text
    assert text.index("-m scripts.fetch_boston") < guard < text.index("-m scripts.fetch_datacommons")
    assert text.rindex("-m scripts.fetch_datacommons") < text.index("-m scripts.preprocess_boston")
    assert "echo \"$DATACOMMONS_API_KEY" not in text and "set -x" not in text
    # From the secret file, the key is set only on the Data Commons command, never exported.
    assert 'DATACOMMONS_API_KEY="$(cat "$DATACOMMONS_API_KEY_FILE")" "$PYTHON" -m scripts.fetch_datacommons' in text
    assert "export DATACOMMONS_API_KEY" not in text


def test_build_script_key_file_is_scoped_to_one_step(tmp_path):
    """Run build_data.sh with stub Python: only the Data Commons step sees the key."""
    import os
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    proj = tmp_path / "proj"
    (proj / "scripts").mkdir(parents=True)
    (proj / "scripts" / "build_data.sh").write_text((root / "scripts" / "build_data.sh").read_text())
    log = tmp_path / "log.txt"
    stub = tmp_path / "py"
    stub.write_text(f'#!/bin/sh\necho "$2 key=${{DATACOMMONS_API_KEY:-none}}" >> "{log}"\n')
    stub.chmod(0o755)
    keyfile = tmp_path / "key"
    keyfile.write_text(FAKE_KEY)
    env = {k: v for k, v in os.environ.items() if k != "DATACOMMONS_API_KEY"}
    env["DATACOMMONS_API_KEY_FILE"] = str(keyfile)
    run = subprocess.run(
        ["bash", str(proj / "scripts" / "build_data.sh"), "--python", str(stub)],
        env=env, capture_output=True, text=True, check=True,
    )
    lines = log.read_text().splitlines()
    assert lines == [
        "scripts.fetch_boston key=none",
        f"scripts.fetch_datacommons key={FAKE_KEY}",
        "scripts.preprocess_boston key=none",
    ]
    assert FAKE_KEY not in run.stdout + run.stderr


# --- census_zip table and runtime ---------------------------------------------------------

def test_load_census(tmp_path):
    (tmp_path / "d.json").write_text(json.dumps({"fetched": "2026-10-01", "places": [
        {"zip": "02120", "housing_units": 5030, "built_before_1940": 1388, "renter_occupied": 4200,
         "owner_occupied": 425, "dates": {"housing_units": "2024"}},
        {"zip": "bad"},
    ]}))
    df = load_census(tmp_path / "d.json")
    assert df.to_dict("records") == [{
        "zip": "02120", "housing_units": 5030, "built_before_1940": 1388, "renter_occupied": 4200,
        "owner_occupied": 425, "year": "2024", "fetched": "2026-10-01",
    }]
    assert load_census(tmp_path / "missing.json") is None


def test_census_for_zip(db, tmp_path):
    c = census_for_zip("01002", db)
    assert (c.pct_built_before_1940, c.pct_renter_occupied, c.year) == (23, 53, "2024")
    assert c.url == "https://datacommons.org/place/zip/01002"
    assert census_for_zip("99999", db) is None
    assert census_for_zip("02128", build_fixture_db(tmp_path / "n.sqlite", with_census=False)) is None
    assert census_for_zip("02128", tmp_path / "missing.sqlite") is None


@pytest.mark.parametrize(
    "address, zip_code",
    [
        ("182 London St 02128", "02128"),  # matched rental
        ("182 London St, East Boston", "02128"),  # matched, ZIP from the city's address
        ("999 London St 02128", "02128"),  # area context
        ("12 Example St, Amherst, MA 01002", "01002"),  # Amherst ZIP typed
        ("12 Example St, Amherst, MA", None),  # no ZIP: don't guess
    ],
)
def test_zip_for_report(db, address, zip_code):
    assert zip_for_report(address, context_for_address(address, db)) == zip_code


def test_census_context_none_without_address(db):
    assert census_context("", None, db) is None


# --- Card ---------------------------------------------------------------------------------

def _post(client, db, address):
    app.dependency_overrides[get_boston_db] = lambda: db
    return client.post("/check", data={"listing": SPARSE, "address": address}, headers=HX).text


def test_card_for_amherst(client, db):
    html = _post(client, db, "12 Example St, Amherst, MA 01002")
    assert "Area housing (U.S. Census via Data Commons)" in html
    assert "About 23% of homes were built in 1939 or earlier." in html
    assert "About 53% of occupied homes are rented." in html
    assert "ending in 2024" in html
    assert "Smoke alarm requirements depend on when a building was built" in html
    assert "Massachusetts smoke alarm rules" in html
    m = re.search(r'<a href="https://datacommons\.org/place/zip/01002"[^>]*>(.*?)</a>', html, re.S)
    assert m and "Data Commons" in m.group(1) and "(opens in a new tab)" in m.group(1)
    assert 'rel="noopener noreferrer"' in m.group(0)
    assert "not this building" in html


def test_card_for_boston(client, db):
    html = _post(client, db, "182 London St, East Boston 02128")
    assert "About 45% of homes were built in 1939 or earlier." in html
    assert "About 67% of occupied homes are rented." in html


def test_no_card_without_data(client, db):
    assert "Area housing" not in _post(client, db, "4 Example St, Worcester, MA 01609")


def test_census_never_used_in_ranking():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for f in (root / "app" / "services" / "ranking.py",):
        src = f.read_text()
        assert "census" not in src.lower() and "construction" not in src.lower()


def test_no_runtime_datacommons_calls():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "app"
    for f in root.rglob("*.py"):
        assert "api.datacommons.org" not in f.read_text(), f


def test_card_copy_rules(client, db):
    html = _post(client, db, "182 London St, East Boston 02128")
    card = html[html.index('id="census-heading"'):]
    card = card[: card.index("</section>")]
    text = re.sub(r"<[^>]+>", " ", card)
    assert "\u2014" not in text and "!" not in text
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM census_zip").fetchone()[0] == 2
