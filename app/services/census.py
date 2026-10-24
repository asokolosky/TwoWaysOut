"""Area housing context by ZIP code (U.S. Census American Community Survey via Data Commons).

The figures are loaded into boston.sqlite's `census_zip` table at build time by
scripts/fetch_datacommons.py and scripts/preprocess_boston.py. The app never calls Data Commons
and never sends an address anywhere. This is context only and is never a ranking input.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.services.address_normalize import parse_address
from app.services.boston import BuildingContext

DATA_COMMONS_PLACE_URL = "https://datacommons.org/place/zip/{zip}"


@dataclass(frozen=True)
class CensusContext:
    zip: str
    housing_units: int
    pct_built_before_1940: int | None  # whole percent of all housing units
    pct_renter_occupied: int | None  # whole percent of occupied homes
    year: str | None  # last year of the ACS 5-year estimate
    url: str


def _pct(part, whole) -> int | None:
    if part is None or not whole:
        return None
    return round(part / whole * 100)


def census_for_zip(zip_code: str | None, db_path: Path) -> CensusContext | None:
    if not zip_code or not Path(db_path).exists():
        return None
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            has = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='census_zip'"
            ).fetchone()
            if not has:
                return None
            r = con.execute("SELECT * FROM census_zip WHERE zip = ?", (zip_code,)).fetchone()
    except sqlite3.Error:
        return None
    if r is None or not r["housing_units"]:
        return None
    occupied = (r["renter_occupied"] or 0) + (r["owner_occupied"] or 0)
    ctx = CensusContext(
        zip=zip_code,
        housing_units=int(r["housing_units"]),
        pct_built_before_1940=_pct(r["built_before_1940"], r["housing_units"]),
        pct_renter_occupied=_pct(r["renter_occupied"], occupied) if r["renter_occupied"] is not None else None,
        year=r["year"],
        url=DATA_COMMONS_PLACE_URL.format(zip=zip_code),
    )
    if ctx.pct_built_before_1940 is None and ctx.pct_renter_occupied is None:
        return None
    return ctx


def zip_for_report(address: str, boston: BuildingContext | None) -> str | None:
    """ZIP for the area card: the matched Boston address's ZIP, else one typed in the address.

    Only ZIPs in the fixed build-time list have rows, so anything else returns no card.
    """
    if boston is not None and boston.match is not None and boston.match.matched and boston.match.zip:
        return boston.match.zip
    if boston is not None and boston.kind == "area" and boston.area and boston.area.area.level == "zip":
        return boston.area.area.area_key
    parsed = parse_address(address or "")
    return parsed.zip if parsed else None


def census_context(address: str, boston: BuildingContext | None, db_path: Path) -> CensusContext | None:
    if not (address or "").strip():
        return None
    return census_for_zip(zip_for_report(address, boston), db_path)
