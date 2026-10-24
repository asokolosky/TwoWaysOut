"""Pipeline entry points and privacy whitelists: fetch_boston, preprocess main, lookup script."""

import io
import json
import re
import sqlite3
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

from scripts import construction, fetch_boston, history, lookup, preprocess_boston
from tests.fixtures.boston_csv import (
    ASSESSMENT_CSV,
    PERMITS_CSV,
    RENTSMART_CSV,
    SAM_CSV,
    VIOLATIONS_CSV,
)
from tests.fixtures.boston_db import build_fixture_db

STEERING = Path(__file__).resolve().parent.parent / ".kiro" / "steering" / "project-rules.md"

# Forbidden fields per dataset, as listed in privacy rule 1 of the steering file.
FORBIDDEN = {
    "Property Assessment": {"OWNER", "MAIL_ADDRESSEE", "MAIL_STREET_ADDRESS", "MAIL_CITY", "MAIL_STATE", "MAIL_ZIP_CODE"},
    "RentSmart": {"owner"},
    "Building violations": {"contact_addr1", "contact_addr2", "contact_city", "contact_state", "contact_zip"},
    "Building permits": {"applicant", "comments"},
}


# --- Whitelists vs. the steering file ------------------------------------------------------

def _steering_forbidden() -> dict[str, set[str]]:
    out = {}
    for line in STEERING.read_text().splitlines():
        m = re.match(r"\s*-\s*(Property Assessment|RentSmart|Building violations|Building permits):\s*(.+)", line)
        if m:
            out[m.group(1)] = set(re.findall(r"`([^`]+)`", m.group(2)))
    return out


def test_steering_lists_match_this_test():
    assert _steering_forbidden() == FORBIDDEN


@pytest.mark.parametrize(
    "dataset, whitelist",
    [
        ("Property Assessment", preprocess_boston.ASSESSMENT_COLUMNS),
        ("RentSmart", history.RENTSMART_COLUMNS),
        ("Building violations", history.VIOLATION_COLUMNS),
        ("Building permits", history.PERMIT_COLUMNS),
        ("Building permits", construction.CONSTRUCTION_COLUMNS),
        ("Building permits", preprocess_boston.PERMIT_READ_COLUMNS),
    ],
)
def test_whitelists_disjoint_from_forbidden_fields(dataset, whitelist):
    forbidden = {f.lower() for f in _steering_forbidden()[dataset]}
    assert not forbidden & {c.lower() for c in whitelist}


def test_sam_whitelist_has_no_owner_or_mail_fields():
    assert not {c for c in preprocess_boston.SAM_COLUMNS if "OWNER" in c or c.startswith("MAIL_")} - {"MAILING_NEIGHBORHOOD"}


def test_construction_read_never_includes_free_text_or_fees():
    for col in ("description", "total_fees", "applicant", "comments"):
        assert col not in preprocess_boston.PERMIT_READ_COLUMNS


# --- fetch_boston (no network) ------------------------------------------------------------

def test_unknown_dataset_exits(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch_boston, "RAW_DIR", tmp_path)
    monkeypatch.setattr(fetch_boston, "download", lambda *a: pytest.fail("should not download"))
    with pytest.raises(SystemExit) as exc:
        fetch_boston.main(["sam", "nope"])
    assert "Unknown dataset(s): nope" in str(exc.value)


def _http_error(code, location=None):
    headers = Message()
    if location:
        headers["Location"] = location
    return urllib.error.HTTPError("https://data.boston.gov/x", code, "redirect", headers, None)


def test_resolve_strips_443_from_redirect(monkeypatch):
    signed = "https://bucket.s3.amazonaws.com:443/file.csv?X-Amz-Signature=abc"

    class Opener:
        def open(self, req, timeout=None):
            assert req.get_method() == "HEAD"
            raise _http_error(302, signed)

    monkeypatch.setattr(fetch_boston.urllib.request, "build_opener", lambda *h: Opener())
    assert fetch_boston._resolve("https://data.boston.gov/x") == "https://bucket.s3.amazonaws.com/file.csv?X-Amz-Signature=abc"


def test_resolve_without_redirect_and_other_errors(monkeypatch):
    class Ok:
        def open(self, req, timeout=None):
            return io.BytesIO(b"")

    monkeypatch.setattr(fetch_boston.urllib.request, "build_opener", lambda *h: Ok())
    assert fetch_boston._resolve("https://data.boston.gov/x") == "https://data.boston.gov/x"

    class NotFound:
        def open(self, req, timeout=None):
            raise _http_error(404)

    monkeypatch.setattr(fetch_boston.urllib.request, "build_opener", lambda *h: NotFound())
    with pytest.raises(urllib.error.HTTPError):
        fetch_boston._resolve("https://data.boston.gov/x")


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_download_streams_to_part_then_replaces(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch_boston, "RAW_DIR", tmp_path)
    monkeypatch.setattr(fetch_boston, "_resolve", lambda url: url)
    (tmp_path / "sam.csv").write_text("old")

    def urlopen(req, timeout=None):
        return _Resp(b"a,b\n1,2\n")

    monkeypatch.setattr(fetch_boston.urllib.request, "urlopen", urlopen)
    dest = fetch_boston.download("sam", "https://example.test/sam.csv")
    assert dest == tmp_path / "sam.csv"
    assert dest.read_text() == "a,b\n1,2\n"
    assert not (tmp_path / "sam.csv.part").exists()


def test_download_failure_keeps_old_file(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch_boston, "RAW_DIR", tmp_path)
    monkeypatch.setattr(fetch_boston, "_resolve", lambda url: url)
    (tmp_path / "sam.csv").write_text("old")

    class Broken(_Resp):
        def read(self, n=-1):
            raise TimeoutError

    monkeypatch.setattr(fetch_boston.urllib.request, "urlopen", lambda req, timeout=None: Broken(b""))
    with pytest.raises(TimeoutError):
        fetch_boston.download("sam", "https://example.test/sam.csv")
    assert (tmp_path / "sam.csv").read_text() == "old"


def _fake_download(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch_boston, "RAW_DIR", tmp_path)
    monkeypatch.setattr(fetch_boston, "download", lambda name, url: tmp_path / f"{name}.csv")
    monkeypatch.setattr(fetch_boston.time, "strftime", lambda fmt: "2026-11-01")


def test_partial_fetch_leaves_snapshot_date_unchanged(monkeypatch, tmp_path):
    (tmp_path / "SNAPSHOT_DATE").write_text("2026-10-24")
    _fake_download(monkeypatch, tmp_path)
    fetch_boston.main(["permits"])
    assert (tmp_path / "SNAPSHOT_DATE").read_text() == "2026-10-24"
    assert json.loads((tmp_path / "SNAPSHOT_DATES.json").read_text()) == {"permits": "2026-11-01"}


def test_full_fetch_updates_snapshot_date(monkeypatch, tmp_path):
    (tmp_path / "SNAPSHOT_DATE").write_text("2026-10-24")
    _fake_download(monkeypatch, tmp_path)
    fetch_boston.main([])
    assert (tmp_path / "SNAPSHOT_DATE").read_text() == "2026-11-01"
    assert set(json.loads((tmp_path / "SNAPSHOT_DATES.json").read_text())) == set(fetch_boston.DATASETS)


def test_snapshot_uses_oldest_dataset(tmp_path):
    (tmp_path / "SNAPSHOT_DATE").write_text("2026-10-24")
    (tmp_path / "SNAPSHOT_DATES.json").write_text(json.dumps({"permits": "2026-11-01", "sam": "2026-11-01"}))
    # assessment has no per-dataset date, so it falls back to the last full fetch.
    assert preprocess_boston.snapshot_for(tmp_path, ["sam", "assessment", "permits"]) == "2026-10-24"
    assert preprocess_boston.snapshot_for(tmp_path, ["sam", "permits"]) == "2026-11-01"
    (tmp_path / "SNAPSHOT_DATE").unlink()
    (tmp_path / "SNAPSHOT_DATES.json").unlink()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", preprocess_boston.snapshot_for(tmp_path, ["sam"]))


# --- preprocess_boston.main ---------------------------------------------------------------

def _raw(tmp_path, names):
    files = {"sam": SAM_CSV, "assessment": ASSESSMENT_CSV, "rentsmart": RENTSMART_CSV,
             "violations": VIOLATIONS_CSV, "permits": PERMITS_CSV}
    raw = tmp_path / "raw"
    raw.mkdir()
    for n in names:
        (raw / f"{n}.csv").write_text(files[n])
    (raw / "SNAPSHOT_DATE").write_text("2026-10-24")
    return raw


def _point_main_at(monkeypatch, tmp_path, raw):
    db = tmp_path / "out" / "boston.sqlite"
    monkeypatch.setattr(preprocess_boston, "RAW_DIR", raw)
    monkeypatch.setattr(preprocess_boston, "DB_PATH", db)
    monkeypatch.setattr(preprocess_boston, "ROOT", tmp_path)
    return db


def _tables(db):
    with sqlite3.connect(db) as con:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_main_exits_when_required_file_missing(monkeypatch, tmp_path):
    raw = _raw(tmp_path, ["sam"])
    db = _point_main_at(monkeypatch, tmp_path, raw)
    with pytest.raises(SystemExit) as exc:
        preprocess_boston.main()
    assert "Missing data/raw/assessment.csv" in str(exc.value)
    assert not db.exists()


def test_main_skips_history_when_files_missing(monkeypatch, tmp_path, capsys):
    raw = _raw(tmp_path, ["sam", "assessment", "rentsmart"])
    db = _point_main_at(monkeypatch, tmp_path, raw)
    preprocess_boston.main()
    assert "History files missing" in capsys.readouterr().out
    assert _tables(db) == {"addresses", "properties", "meta"}


def test_main_full_build(monkeypatch, tmp_path, capsys):
    raw = _raw(tmp_path, ["sam", "assessment", "rentsmart", "violations", "permits"])
    (raw / "datacommons.json").write_text(json.dumps({"fetched": "2026-10-20", "places": [
        {"zip": "02128", "housing_units": 10, "built_before_1940": 5, "renter_occupied": 6,
         "owner_occupied": 3, "dates": {"housing_units": "2024"}}]}))
    db = _point_main_at(monkeypatch, tmp_path, raw)
    preprocess_boston.main()
    out = capsys.readouterr().out
    assert "construction sites" in out and "Census ZIP rows" in out
    assert {"records", "permits", "area_stats", "construction", "census_zip"} <= _tables(db)
    with sqlite3.connect(db) as con:
        meta = dict(con.execute("SELECT key, value FROM meta"))
        text = " ".join(str(v) for row in con.execute("SELECT * FROM construction") for v in row)
    assert meta["snapshot_date"] == "2026-10-24" and meta["construction"] == "4"
    assert "TEST APPLICANT" not in text and "SECRET" not in text


# --- scripts/lookup.py --------------------------------------------------------------------

@pytest.fixture
def lookup_db(tmp_path, monkeypatch):
    db = build_fixture_db(tmp_path / "boston.sqlite")
    real = lookup.lookup
    monkeypatch.setattr(lookup, "lookup", lambda address: real(address, db))
    return db


def test_lookup_usage(monkeypatch):
    monkeypatch.setattr("sys.argv", ["lookup"])
    with pytest.raises(SystemExit) as exc:
        lookup.main()
    assert "Usage" in str(exc.value)


def test_lookup_matched(monkeypatch, capsys, lookup_db):
    monkeypatch.setattr("sys.argv", ["lookup", "182 London St 02128"])
    lookup.main()
    out = capsys.readouterr().out
    assert "Matched (exact): 182 London St, East Boston 02128" in out
    assert "parcel 0106069000" in out
    assert "Rental: yes (multi-family building)" in out
    assert "Year built: 1910" in out
    assert "OWNER" not in out.upper()


def test_lookup_unmatched_and_ambiguous(monkeypatch, capsys, lookup_db):
    monkeypatch.setattr("sys.argv", ["lookup", "999 Nowhere Rd"])
    lookup.main()
    assert "No match: We couldn't find that address" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["lookup", "10", "Oak", "Ave"])
    lookup.main()
    out = capsys.readouterr().out
    assert "Add the ZIP code" in out and "Possible ZIP codes: 02122, 02131" in out


def test_lookup_no_assessment_record(monkeypatch, capsys, tmp_path):
    db = build_fixture_db(tmp_path / "b.sqlite")
    with sqlite3.connect(db) as con:
        con.execute("DELETE FROM properties WHERE parcel_id = '0106069000'")
    real = lookup.lookup
    monkeypatch.setattr(lookup, "lookup", lambda address: real(address, db))
    monkeypatch.setattr("sys.argv", ["lookup", "182 London St 02128"])
    lookup.main()
    assert "No assessment record for this parcel." in capsys.readouterr().out
