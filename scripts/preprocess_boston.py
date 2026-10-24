"""Build data/boston.sqlite from the raw Analyze Boston downloads.

Usage:
    python -m scripts.preprocess_boston

Privacy: only whitelisted columns are read. Owner names, mailing addresses, and contact
addresses are never loaded, so they can't reach the app's database.

Tables:
    addresses   SAM building-level addresses -> sam_id, parcel, ward, coordinates
    properties  one row per building parcel: land use, units, rental status, year built, heat
    records, permits, area_stats   see scripts/history.py
    construction  block-level new construction and major work nearby (scripts/construction.py)
    census_zip  U.S. Census housing figures by ZIP via Data Commons, when
                data/raw/datacommons.json exists (scripts/fetch_datacommons.py). Context only,
                never a ranking input.
    meta        snapshot date and row counts
"""

import json
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

from app.services.address_normalize import number_value, street_key
from scripts import construction, history

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "boston.sqlite"

# Permits are read once, with the union of the history and construction whitelists. Neither
# includes applicant, comments, description, or total_fees.
PERMIT_READ_COLUMNS = sorted(set(history.PERMIT_COLUMNS) | set(construction.CONSTRUCTION_COLUMNS))
CENSUS_FILE = "datacommons.json"
CENSUS_FIELDS = ("housing_units", "built_before_1940", "renter_occupied", "owner_occupied")

SAM_COLUMNS = [
    "SAM_ADDRESS_ID", "BUILDING_ID", "RELATIONSHIP_TYPE", "FULL_ADDRESS", "STREET_NUMBER",
    "IS_RANGE", "RANGE_FROM", "RANGE_TO", "UNIT", "FULL_STREET_NAME", "ZIP_CODE", "WARD",
    "PARCEL_ID", "MAILING_NEIGHBORHOOD", "POINT_X", "POINT_Y",
]
# Deliberately excludes OWNER, MAIL_ADDRESSEE, MAIL_STREET_ADDRESS, MAIL_CITY, MAIL_STATE,
# MAIL_ZIP_CODE, and assessed values.
ASSESSMENT_COLUMNS = [
    "PID", "CM_ID", "GIS_ID", "LU", "LU_DESC", "OWN_OCC", "RES_UNITS", "YR_BUILT",
    "YR_REMODEL", "HEAT_TYPE",
]

MULTI_FAMILY = {"R2", "R3", "R4", "A", "RC"}
# Unit counts implied by the land use code when RES_UNITS is blank.
KNOWN_UNITS = {"R1": 1, "R2": 2, "R3": 3, "CD": 1}
SINGLE_UNIT = {"R1", "CD"}
CURRENT_YEAR = int(time.strftime("%Y"))


def _pid(s: pd.Series) -> pd.Series:
    """Parcels as 10-digit strings. Older assessment files end PIDs with '_'."""
    return s.astype("string").str.strip().str.rstrip("_").str.zfill(10)


def _year(s: pd.Series) -> pd.Series:
    y = pd.to_numeric(s, errors="coerce")
    return y.where((y >= 1700) & (y <= CURRENT_YEAR)).astype("Int64")


# --- Addresses ----------------------------------------------------------------------------

def build_addresses(sam: pd.DataFrame) -> pd.DataFrame:
    """One row per building-level address (rows without a unit)."""
    sam = sam[list(SAM_COLUMNS)].copy()
    base = sam[sam["UNIT"].isna() | (sam["UNIT"].astype("string").str.strip() == "")]
    base = base[base["PARCEL_ID"].notna() & base["FULL_STREET_NAME"].notna()]

    num = base["STREET_NUMBER"].astype("string")
    lo = base["RANGE_FROM"].where(base["IS_RANGE"] == "1", num).map(number_value)
    hi = base["RANGE_TO"].where(base["IS_RANGE"] == "1", num).map(number_value)

    out = pd.DataFrame(
        {
            "sam_id": base["SAM_ADDRESS_ID"].astype("string"),
            "building_id": base["BUILDING_ID"].astype("string"),
            "is_primary": (base["RELATIONSHIP_TYPE"] == "1").astype(int),
            "number_text": num.str.upper(),
            "number_from": lo,
            "number_to": hi,
            "street_key": base["FULL_STREET_NAME"].map(street_key),
            "zip": base["ZIP_CODE"].astype("string").str.zfill(5),
            "ward": pd.to_numeric(base["WARD"], errors="coerce").astype("Int64"),
            "neighborhood": base["MAILING_NEIGHBORHOOD"].astype("string"),
            "parcel_id": _pid(base["PARCEL_ID"]),
            "display_address": base["FULL_ADDRESS"].astype("string"),
            "lat": pd.to_numeric(base["POINT_Y"], errors="coerce"),
            "lon": pd.to_numeric(base["POINT_X"], errors="coerce"),
        }
    )
    out = out.dropna(subset=["number_from", "number_to"])
    out["number_from"] = out["number_from"].astype(int)
    out["number_to"] = out["number_to"].astype(int)
    swap = out["number_from"] > out["number_to"]
    out.loc[swap, ["number_from", "number_to"]] = out.loc[swap, ["number_to", "number_from"]].values
    return out.reset_index(drop=True)


# --- Properties and rental classification -------------------------------------------------

def _mode(s: pd.Series):
    s = s.dropna()
    return s.mode().iloc[0] if not s.empty else None


def classify(lu: str | None, own_occ: str | None, unit_count: int, rental_units: int) -> tuple[bool, str]:
    """Return (is_rental, reason). 'Rental' here means likely rented, from assessment data."""
    if lu in MULTI_FAMILY:
        return True, "multi-family building"
    if lu == "CM":
        if unit_count == 0:
            return False, "condo building with no residential units"
        if rental_units > 0:
            return True, f"condo building with {rental_units} of {unit_count} units not owner-occupied"
        return False, "condo building where every unit is owner-occupied"
    if lu in SINGLE_UNIT:
        if own_occ == "N":
            return True, "not owner-occupied"
        return False, "owner-occupied single unit"
    if lu == "E":
        return False, "tax-exempt property (not classified)"
    return False, "not a residential building"


def build_properties(assess: pd.DataFrame) -> pd.DataFrame:
    """One row per building parcel. Condo units roll up to their condo main parcel (CM_ID)."""
    a = assess[list(ASSESSMENT_COLUMNS)].copy()
    a["PID"] = _pid(a["PID"])
    a["CM_ID"] = _pid(a["CM_ID"]).where(a["CM_ID"].notna())
    a["building_parcel"] = a["CM_ID"].fillna(a["PID"])
    a["YR_BUILT"] = _year(a["YR_BUILT"])
    a["YR_REMODEL"] = _year(a["YR_REMODEL"])
    a["RES_UNITS"] = pd.to_numeric(a["RES_UNITS"], errors="coerce")
    a["LU"] = a["LU"].astype("string").str.split(" ").str[0]  # "RL - RL" -> "RL"

    rows = []
    for parcel, g in a.groupby("building_parcel", sort=False):
        main = g[g["PID"] == parcel]
        main = main.iloc[0] if not main.empty else g.iloc[0]
        units = g[g["LU"] == "CD"]
        lu = main["LU"]
        if lu == "CD":  # unit row with no CM record in this file
            lu = "CM" if len(units) > 1 else "CD"
        if lu == "CM":
            unit_count = len(units)
        elif pd.notna(main["RES_UNITS"]):
            unit_count = int(main["RES_UNITS"])
        else:
            unit_count = KNOWN_UNITS.get(lu)
        rental_units = int((units["OWN_OCC"] == "N").sum()) if lu == "CM" else 0
        own_occ = None if lu == "CM" else main["OWN_OCC"]
        is_rental, reason = classify(lu, own_occ, unit_count or 0, rental_units)
        rows.append(
            {
                "parcel_id": parcel,
                "land_use": lu,
                "land_use_desc": "CONDOMINIUM BUILDING" if lu == "CM" else main["LU_DESC"],
                "units": unit_count,
                "owner_occupied": None if own_occ is None else int(own_occ == "Y"),
                "is_rental": int(is_rental),
                "rental_reason": reason,
                "year_built": _mode(g["YR_BUILT"]) if pd.isna(main["YR_BUILT"]) else main["YR_BUILT"],
                "year_remodeled": g["YR_REMODEL"].max() if g["YR_REMODEL"].notna().any() else None,
                "heat_type": main["HEAT_TYPE"] if pd.notna(main["HEAT_TYPE"]) else _mode(g["HEAT_TYPE"]),
            }
        )
    out = pd.DataFrame(rows)
    for col in ("units", "owner_occupied", "year_built", "year_remodeled"):
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")
    return out


# --- Main ---------------------------------------------------------------------------------

def write_db(
    addresses: pd.DataFrame,
    properties: pd.DataFrame,
    db_path: Path,
    snapshot: str,
    history: dict[str, pd.DataFrame] | None = None,
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".sqlite.tmp")
    tmp.unlink(missing_ok=True)
    history = history or {}
    with sqlite3.connect(tmp) as con:
        addresses.to_sql("addresses", con, index=False)
        properties.to_sql("properties", con, index=False)
        for name, df in history.items():
            df.to_sql(name, con, index=False)
        meta = [
            ("snapshot_date", snapshot),
            ("addresses", str(len(addresses))),
            ("properties", str(len(properties))),
            *((name, str(len(df))) for name, df in history.items()),
        ]
        pd.DataFrame(meta, columns=["key", "value"]).to_sql("meta", con, index=False)
        con.execute("CREATE INDEX idx_addr_street ON addresses (street_key, zip)")
        con.execute("CREATE INDEX idx_addr_parcel ON addresses (parcel_id)")
        con.execute("CREATE UNIQUE INDEX idx_prop_parcel ON properties (parcel_id)")
        if "records" in history:
            con.execute("CREATE INDEX idx_records_parcel ON records (parcel_id, date)")
        if "permits" in history:
            con.execute("CREATE INDEX idx_permits_parcel ON permits (parcel_id, issued_date)")
        if "area_stats" in history:
            con.execute("CREATE UNIQUE INDEX idx_area ON area_stats (level, area_key)")
        if "construction" in history:
            # Bounding-box lookups: latitude range first, then longitude.
            con.execute("CREATE INDEX idx_construction_latlon ON construction (lat, lon)")
        if "census_zip" in history:
            con.execute("CREATE UNIQUE INDEX idx_census_zip ON census_zip (zip)")
    tmp.replace(db_path)


def load_census(path: Path) -> pd.DataFrame | None:
    """census_zip table from data/raw/datacommons.json (written by scripts.fetch_datacommons)."""
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    rows = []
    for p in data.get("places", []):
        z = str(p.get("zip", ""))
        if not (z.isdigit() and len(z) == 5):
            continue
        dates = [d for d in (p.get("dates") or {}).values() if d]
        rows.append(
            {
                "zip": z,
                **{f: p.get(f) for f in CENSUS_FIELDS},
                "year": max(dates) if dates else None,
                "fetched": data.get("fetched"),
            }
        )
    df = pd.DataFrame(rows, columns=["zip", *CENSUS_FIELDS, "year", "fetched"])
    for f in CENSUS_FIELDS:
        df[f] = pd.to_numeric(df[f], errors="coerce").astype("Int64")
    return df


SNAPSHOT_DATES_FILE = "SNAPSHOT_DATES.json"


def snapshot_for(raw_dir: Path, datasets: list[str]) -> str:
    """Oldest download date among the datasets used, so the card never overstates freshness.

    Uses per-dataset dates from SNAPSHOT_DATES.json (written by fetch_boston), falling back to
    SNAPSHOT_DATE (last full fetch) for datasets without a recorded date, then to today.
    """
    per = {}
    f = raw_dir / SNAPSHOT_DATES_FILE
    if f.exists():
        try:
            per = json.loads(f.read_text())
        except json.JSONDecodeError:
            per = {}
    full = raw_dir / "SNAPSHOT_DATE"
    full_date = full.read_text().strip() if full.exists() else None
    dates = [per.get(n) or full_date for n in datasets]
    dates = [d for d in dates if d]
    return min(dates) if dates else time.strftime("%Y-%m-%d")


def build_history(
    sam: pd.DataFrame,
    assess: pd.DataFrame,
    addresses: pd.DataFrame,
    properties: pd.DataFrame,
    rentsmart: pd.DataFrame,
    violations: pd.DataFrame,
    permits: pd.DataFrame,
    snapshot: str,
) -> dict[str, pd.DataFrame]:
    pmap = history.parcel_map(assess)
    smap = history.sam_parcel_map(sam)
    all_records = history.build_records(rentsmart, violations, pmap, smap)
    out = {
        # Building-level tables: rental buildings only.
        "records": history.rental_only(all_records.drop(columns=["zip", "ward"]), properties),
        "permits": history.rental_only(history.build_permits(permits, pmap, smap), properties),
        # Area statistics: all buildings, so neighborhood context is complete.
        "area_stats": history.build_area_stats(all_records, properties, addresses, snapshot),
    }
    if set(construction.CONSTRUCTION_COLUMNS) <= set(permits.columns):
        # Block-level nearby construction (all buildings; never shown for the matched parcel).
        out["construction"] = construction.build_construction(permits, pmap, smap, snapshot)
    return out


def main() -> None:
    for name in ("sam", "assessment"):
        if not (RAW_DIR / f"{name}.csv").exists():
            sys.exit(f"Missing data/raw/{name}.csv. Run: python -m scripts.fetch_boston sam assessment")
    start = time.monotonic()
    sam = pd.read_csv(RAW_DIR / "sam.csv", dtype=str, usecols=SAM_COLUMNS)
    assess = pd.read_csv(RAW_DIR / "assessment.csv", dtype=str, usecols=ASSESSMENT_COLUMNS)
    addresses = build_addresses(sam)
    properties = build_properties(assess)

    hist = None
    history_files = {"rentsmart": history.RENTSMART_COLUMNS, "violations": history.VIOLATION_COLUMNS, "permits": PERMIT_READ_COLUMNS}
    used = ["sam", "assessment"]
    if all((RAW_DIR / f"{n}.csv").exists() for n in history_files):
        used += list(history_files)
        snapshot = snapshot_for(RAW_DIR, used)
        raw = {
            n: pd.read_csv(RAW_DIR / f"{n}.csv", dtype=str, usecols=cols)
            for n, cols in history_files.items()
        }
        hist = build_history(sam, assess, addresses, properties, raw["rentsmart"], raw["violations"], raw["permits"], snapshot)
    else:
        snapshot = snapshot_for(RAW_DIR, used)
        print("History files missing; run: python -m scripts.fetch_boston rentsmart violations permits")

    census = load_census(RAW_DIR / CENSUS_FILE)
    if census is not None:
        hist = {**(hist or {}), "census_zip": census}
    else:
        print("No data/raw/datacommons.json; area housing (Census) data skipped.")

    write_db(addresses, properties, DB_PATH, snapshot, hist)
    extra = ""
    if hist and "records" in hist:
        extra += f", {len(hist['records']):,} fire-related records, {len(hist['permits']):,} permits"
    if hist and "construction" in hist:
        extra += f", {len(hist['construction']):,} construction sites"
    if hist and "census_zip" in hist:
        extra += f", {len(hist['census_zip']):,} Census ZIP rows"
    print(
        f"Wrote {DB_PATH.relative_to(ROOT)}: {len(addresses):,} addresses, "
        f"{len(properties):,} building parcels ({int(properties.is_rental.sum()):,} likely rentals)"
        + extra
        + f" in {time.monotonic() - start:.0f}s"
    )


if __name__ == "__main__":
    main()
