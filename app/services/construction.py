"""Nearby construction for a student report.

Boston: new construction and major work near the matched address, from the `construction` table
built by scripts/construction.py. Shown for any matched Boston address, rental or not, because
it's about nearby sites, not the building's own history. Sites are shown at block level only
("100 block of Main St") with work type, month issued, and a rough distance (privacy rule 8).
The matched building's own parcel is always left out.

Amherst: there's no bulk permit data, so the card links the town's permit portal and suggests
asking the landlord. Other towns: suggest asking the town building department.

Never a ranking input.
"""

import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.services.address_normalize import parse_address
from app.services.boston import BuildingContext

RADIUS_M = 250
LIMIT = 8
NEXT_DOOR_M = 60
ROUND_TO_M = 50
# A site with no parcel this close to the matched point is treated as the building itself.
SAME_POINT_M = 10
EARTH_RADIUS_M = 6_371_000
METERS_PER_DEG_LAT = 111_320

AMHERST_ZIPS = frozenset({"01002", "01003", "01004", "01059"})
AMHERST_PERMIT_PORTAL = "https://amherstma.portal.opengov.com"


@dataclass(frozen=True)
class ConstructionSite:
    block_label: str
    kind: str  # "new_construction" or "major_work"
    work_label: str
    issued_month: str  # YYYY-MM
    status: str | None
    distance_m: int  # rounded to the nearest 50 m
    next_door: bool


@dataclass(frozen=True)
class ConstructionContext:
    kind: Literal["boston", "amherst", "other"]
    sites: tuple[ConstructionSite, ...] = field(default_factory=tuple)
    radius_m: int = RADIUS_M
    snapshot_date: str | None = None
    portal_url: str | None = None

    @property
    def any_next_door(self) -> bool:
        return any(s.next_door for s in self.sites)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def round_distance(meters: float) -> int:
    """Nearest 50 m, never below 50 so nothing reads as "0 m away"."""
    return max(ROUND_TO_M, int(round(meters / ROUND_TO_M)) * ROUND_TO_M)


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def has_construction_table(db_path: Path) -> bool:
    if not Path(db_path).exists():
        return False
    try:
        with _connect(db_path) as con:
            row = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='construction'"
            ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def nearby_construction(
    lat: float,
    lon: float,
    db_path: Path,
    exclude_parcels: tuple[str, ...] = (),
    radius_m: int = RADIUS_M,
    limit: int = LIMIT,
) -> list[ConstructionSite]:
    """Sites within radius_m of (lat, lon), nearest first. Bounding box in SQL, then haversine."""
    dlat = radius_m / METERS_PER_DEG_LAT
    dlon = radius_m / (METERS_PER_DEG_LAT * max(math.cos(math.radians(lat)), 0.01))
    excluded = [p for p in exclude_parcels if p]
    not_in = f"AND (parcel_id IS NULL OR parcel_id NOT IN ({','.join('?' * len(excluded))}))" if excluded else ""
    sql = f"""
        SELECT parcel_id, lat, lon, block_label, kind, work_label, issued_month, status
        FROM construction
        WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? {not_in}
    """
    with _connect(db_path) as con:
        rows = con.execute(sql, (lat - dlat, lat + dlat, lon - dlon, lon + dlon, *excluded)).fetchall()

    found = []
    for r in rows:
        d = haversine_m(lat, lon, r["lat"], r["lon"])
        if d > radius_m:
            continue
        if r["parcel_id"] is None and d < SAME_POINT_M:
            continue  # probably the matched building itself
        found.append((d, r))
    found.sort(key=lambda x: (x[0], x[1]["block_label"]))
    # Several parcels on one block with the same work (e.g. a row of demolitions) read as one
    # line; keep the nearest.
    seen: set[tuple[str, str]] = set()
    unique = []
    for d, r in found:
        key = (r["block_label"], r["work_label"])
        if key not in seen:
            seen.add(key)
            unique.append((d, r))
    found = unique
    return [
        ConstructionSite(
            block_label=r["block_label"],
            kind=r["kind"],
            work_label=r["work_label"],
            issued_month=r["issued_month"],
            status=r["status"],
            distance_m=round_distance(d),
            next_door=d < NEXT_DOOR_M,
        )
        for d, r in found[:limit]
    ]


def is_amherst(address: str) -> bool:
    parsed = parse_address(address or "")
    if parsed is None:
        return False
    if parsed.zip:
        return parsed.zip in AMHERST_ZIPS
    return bool(parsed.place) and "AMHERST" in parsed.place.split()


def construction_context(
    address: str, boston: BuildingContext | None, db_path: Path, snapshot_date: str | None = None
) -> ConstructionContext | None:
    """Card data for nearby construction, or None when there's nothing to show."""
    if not (address or "").strip():
        return None
    match = boston.match if boston else None
    if match is not None and match.matched and match.lat is not None and match.lon is not None:
        if not has_construction_table(db_path):
            return None
        own = (match.parcel_id, match.building.parcel_id if match.building else None)
        sites = nearby_construction(match.lat, match.lon, db_path, exclude_parcels=tuple(p for p in own if p))
        return ConstructionContext(kind="boston", sites=tuple(sites), snapshot_date=snapshot_date)
    if is_amherst(address):
        return ConstructionContext(kind="amherst", portal_url=AMHERST_PERMIT_PORTAL)
    if match is not None and match.reason == "outside_boston":
        return ConstructionContext(kind="other")
    # Boston area-only or unmatched: no building point, so nothing to measure from.
    return None
