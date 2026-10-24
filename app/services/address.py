"""Match a typed address to a Boston SAM address and building parcel, then report rental status.

Matching (exact first, looser only when needed):
1. Same normalized street, house number inside the SAM number range ("183 State St" matches
   "181-183 State St"), and same ZIP if one was given.
2. If the street wasn't found, retry without the suffix ("182 London" -> "LONDON ST").
3. If several ZIPs remain and no ZIP was given, use the neighborhood if one was typed;
   otherwise ask for a ZIP rather than guess.
Anything that doesn't match returns a result with a reason, never an exception.
"""

import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.services.address_normalize import ParsedAddress, parse_address

DEFAULT_DB = Path(__file__).resolve().parent.parent.parent / "data" / "boston.sqlite"

# Reasons shown to students when there's no building match.
REASONS = {
    "no_number": "We couldn't find a street number in that address.",
    "outside_boston": "Building records are only available for Boston addresses.",
    "not_found": "We couldn't find that address in Boston's address list.",
    "ambiguous": "That street name exists in more than one Boston neighborhood. Add the ZIP code.",
    "data_unavailable": "Boston building data isn't loaded on this server.",
}


@dataclass(frozen=True)
class PropertyInfo:
    parcel_id: str
    land_use: str | None
    land_use_desc: str | None
    units: int | None
    is_rental: bool
    rental_reason: str
    year_built: int | None
    year_remodeled: int | None
    heat_type: str | None


@dataclass(frozen=True)
class AddressMatch:
    matched: bool
    reason: str | None = None  # key into REASONS when not matched
    match_type: str | None = None  # "exact", "range", or "no_suffix"
    sam_id: str | None = None
    parcel_id: str | None = None
    display_address: str | None = None
    zip: str | None = None
    ward: int | None = None
    neighborhood: str | None = None
    lat: float | None = None
    lon: float | None = None
    building: PropertyInfo | None = None
    candidates: tuple[str, ...] = field(default_factory=tuple)  # ZIPs when ambiguous

    @property
    def reason_text(self) -> str | None:
        return REASONS.get(self.reason) if self.reason else None

    @property
    def is_rental(self) -> bool:
        return bool(self.building and self.building.is_rental)


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


@lru_cache(maxsize=4)
def _known_places(db_path: str) -> tuple[frozenset[str], frozenset[str]]:
    with _connect(Path(db_path)) as con:
        zips = frozenset(r[0] for r in con.execute("SELECT DISTINCT zip FROM addresses") if r[0])
        hoods = frozenset(
            r[0].upper() for r in con.execute("SELECT DISTINCT neighborhood FROM addresses") if r[0]
        )
    return zips, hoods | {"BOSTON"}


def _candidates(con: sqlite3.Connection, p: ParsedAddress, street_sql: str, street_arg: str) -> list[sqlite3.Row]:
    sql = f"""
        SELECT * FROM addresses
        WHERE {street_sql}
          AND number_from <= ? AND number_to >= ?
        ORDER BY
          (number_from = ? AND number_to = ?) DESC,  -- exact number first
          is_primary DESC,
          (number_to - number_from) ASC
    """
    return con.execute(sql, (street_arg, p.number_from, p.number_to, p.number_from, p.number_to)).fetchall()


def _property(con: sqlite3.Connection, parcel_id: str) -> PropertyInfo | None:
    row = con.execute("SELECT * FROM properties WHERE parcel_id = ?", (parcel_id,)).fetchone()
    if row is None:
        return None
    return PropertyInfo(
        parcel_id=row["parcel_id"],
        land_use=row["land_use"],
        land_use_desc=row["land_use_desc"],
        units=row["units"],
        is_rental=bool(row["is_rental"]),
        rental_reason=row["rental_reason"],
        year_built=row["year_built"],
        year_remodeled=row["year_remodeled"],
        heat_type=row["heat_type"],
    )


def lookup(address: str, db_path: Path = DEFAULT_DB) -> AddressMatch:
    parsed = parse_address(address)
    if parsed is None:
        return AddressMatch(matched=False, reason="no_number")
    if not Path(db_path).exists():
        return AddressMatch(matched=False, reason="data_unavailable")

    zips, places = _known_places(str(db_path))
    if parsed.zip and parsed.zip not in zips:
        return AddressMatch(matched=False, reason="outside_boston")
    if not parsed.zip and parsed.place and parsed.place not in places:
        return AddressMatch(matched=False, reason="outside_boston")

    with _connect(Path(db_path)) as con:
        rows = _candidates(con, parsed, "street_key = ?", parsed.street)
        match_type = None
        if not rows and " " not in parsed.street:
            # Typed without a suffix: "182 London".
            rows = _candidates(con, parsed, "street_key LIKE ?", parsed.street + " %")
            match_type = "no_suffix"

        if parsed.zip:
            rows = [r for r in rows if r["zip"] == parsed.zip]
        elif parsed.place and parsed.place != "BOSTON":
            in_place = [r for r in rows if (r["neighborhood"] or "").upper() == parsed.place]
            rows = in_place or rows

        if not rows:
            return AddressMatch(matched=False, reason="not_found")

        # Different streets (no-suffix search) or ZIPs still in play: don't guess.
        distinct = {(r["street_key"], r["zip"]) for r in rows}
        if len(distinct) > 1:
            return AddressMatch(
                matched=False,
                reason="ambiguous",
                candidates=tuple(sorted({r["zip"] for r in rows})),
            )

        best = rows[0]
        if match_type is None:
            exact = best["number_from"] == parsed.number_from and best["number_to"] == parsed.number_to
            match_type = "exact" if exact else "range"

        return AddressMatch(
            matched=True,
            match_type=match_type,
            sam_id=best["sam_id"],
            parcel_id=best["parcel_id"],
            display_address=best["display_address"],
            zip=best["zip"],
            ward=best["ward"],
            neighborhood=best["neighborhood"],
            lat=best["lat"],
            lon=best["lon"],
            building=_property(con, best["parcel_id"]),
        )
