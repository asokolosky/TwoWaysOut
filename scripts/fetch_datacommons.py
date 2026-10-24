"""Download area housing figures (U.S. Census ACS via Data Commons) into data/raw/datacommons.json.

Usage:
    DATACOMMONS_API_KEY=... python -m scripts.fetch_datacommons

Runs at build time only; the app never calls Data Commons. The place list is fixed: every Boston
ZIP in data/boston.sqlite (or data/raw/sam.csv if the database isn't built yet) plus the
Amherst-area ZIPs. No student or tenant address is ever sent.

Without DATACOMMONS_API_KEY the script prints a message and exits 0, so builds still work.
The key is read from the environment and never printed or written anywhere.
"""

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "boston.sqlite"
OUT_NAME = "datacommons.json"

API_URL = "https://api.datacommons.org/v2/observation"
AMHERST_ZIPS = ("01002", "01003", "01004", "01059")
# Statistical variable dcids, checked against datacommons.org (October 2026). All four are
# U.S. Census American Community Survey 5-year estimates for ZIP code areas.
VARIABLES = {
    "housing_units": "Count_HousingUnit",
    "built_before_1940": "Count_HousingUnit_Before1939DateBuilt",  # built 1939 or earlier
    "renter_occupied": "Count_HousingUnit_RenterOccupied",
    "owner_occupied": "Count_HousingUnit_OwnerOccupied",
}
PREFERRED_IMPORT = "CensusACS5YearSurvey"
BATCH = 50
HEADERS = {"User-Agent": "TwoWaysOut/0.1 (hackathon)", "Content-Type": "application/json"}


def boston_zips(db_path: Path = DB_PATH, raw_dir: Path = RAW_DIR) -> list[str]:
    """Boston ZIPs from the built database, else from the SAM download (ZIP column only)."""
    if db_path.exists():
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
            rows = con.execute("SELECT DISTINCT zip FROM addresses WHERE zip IS NOT NULL").fetchall()
        return sorted({r[0] for r in rows if r[0] and r[0].isdigit() and len(r[0]) == 5})
    sam = raw_dir / "sam.csv"
    if sam.exists():
        z = pd.read_csv(sam, dtype=str, usecols=["ZIP_CODE"])["ZIP_CODE"].dropna().str.zfill(5)
        return sorted({v for v in z if v.isdigit() and len(v) == 5})
    return []


def place_list(db_path: Path = DB_PATH, raw_dir: Path = RAW_DIR) -> list[str]:
    return sorted(set(boston_zips(db_path, raw_dir)) | set(AMHERST_ZIPS))


def _post(body: dict, key: str, opener=urllib.request.urlopen) -> dict:
    # The key goes in a header, not the URL, so it can't end up in a logged URL.
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode(), headers={**HEADERS, "X-API-Key": key}, method="POST"
    )
    with opener(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _pick_facet(ordered: list[dict], facets: dict) -> dict | None:
    """Prefer the Census ACS 5-year facet; otherwise the first facet Data Commons ranks."""
    usable = [f for f in ordered if f.get("observations")]
    for f in usable:
        if facets.get(f.get("facetId"), {}).get("importName") == PREFERRED_IMPORT:
            return f
    return usable[0] if usable else None


def parse_response(data: dict, places: dict[str, dict]) -> None:
    """Merge one /v2/observation response into `places` ({zip: {...}})."""
    facets = data.get("facets") or {}
    for field, var in VARIABLES.items():
        by_entity = (data.get("byVariable") or {}).get(var, {}).get("byEntity") or {}
        for dcid, entry in by_entity.items():
            if not dcid.startswith("zip/"):
                continue
            facet = _pick_facet(entry.get("orderedFacets") or [], facets)
            if facet is None:
                continue
            obs = facet["observations"][-1]
            info = facets.get(facet.get("facetId"), {})
            place = places.setdefault(dcid[4:], {"zip": dcid[4:]})
            place[field] = obs.get("value")
            place.setdefault("dates", {})[field] = obs.get("date")
            place.setdefault("provenance", {})[field] = {
                k: info[k] for k in ("importName", "provenanceUrl", "measurementMethod") if k in info
            }


def fetch(zips: list[str], key: str, opener=urllib.request.urlopen) -> dict[str, dict]:
    places: dict[str, dict] = {}
    for i in range(0, len(zips), BATCH):
        body = {
            "date": "LATEST",
            "variable": {"dcids": list(VARIABLES.values())},
            "entity": {"dcids": [f"zip/{z}" for z in zips[i : i + BATCH]]},
            "select": ["entity", "variable", "date", "value"],
        }
        parse_response(_post(body, key, opener), places)
    return places


def main(opener=urllib.request.urlopen, raw_dir: Path = RAW_DIR, db_path: Path = DB_PATH) -> int:
    # Either spelling works; .env in this project uses DATA_COMMONS_API_KEY.
    key = (os.environ.get("DATACOMMONS_API_KEY") or os.environ.get("DATA_COMMONS_API_KEY") or "").strip()
    if not key:
        print("DATACOMMONS_API_KEY is not set; skipping Data Commons area housing data.")
        return 0
    zips = place_list(db_path, raw_dir)
    if not zips:
        print("No ZIP codes to fetch (build boston.sqlite or download sam.csv first).")
        return 0
    try:
        places = fetch(zips, key, opener)
    except urllib.error.HTTPError as exc:
        # Never include the request (and its key header) in the message.
        print(f"Data Commons request failed: HTTP {exc.code}. Skipping area housing data.", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Data Commons request failed: {type(exc).__name__}. Skipping area housing data.", file=sys.stderr)
        return 1
    raw_dir.mkdir(parents=True, exist_ok=True)
    out = {
        "source": "Data Commons (datacommons.org), U.S. Census American Community Survey",
        "api": API_URL,
        "fetched": time.strftime("%Y-%m-%d"),
        "variables": VARIABLES,
        "places": [places[z] for z in sorted(places)],
    }
    tmp = raw_dir / (OUT_NAME + ".part")
    tmp.write_text(json.dumps(out, indent=1))
    tmp.replace(raw_dir / OUT_NAME)
    print(f"Wrote data/raw/{OUT_NAME}: {len(places)} of {len(zips)} ZIP codes had data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
