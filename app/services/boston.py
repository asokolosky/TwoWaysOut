"""Boston building context for a student report: building history for rentals, or area stats.

    context_for_address("182 London St 02128")
      -> BuildingContext(kind="building", history=BuildingHistory(...))   matched rental
      -> BuildingContext(kind="area", area=AreaContext(...), reason=...)  matched non-rental,
                                                                           or unmatched Boston ZIP
      -> BuildingContext(kind="none", reason=...)                          outside Boston / no data
"""

import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

from app.services.address import DEFAULT_DB, AddressMatch, PropertyInfo, _property, lookup
from app.services.address_normalize import parse_address
from app.services.fire_categories import CATEGORIES

RECENT_LIMIT = 8
SOURCE_NAMES = {
    "rentsmart": "RentSmart (Boston ISD and 311)",
    "isd_violations": "ISD Building and Property Violations",
}
PERMIT_LABELS = {
    "fire_alarm": "Fire alarm work",
    "sprinkler": "Sprinkler work",
    "electrical": "Electrical work",
}
DATA_SOURCES = (
    "Analyze Boston: RentSmart, Building and Property Violations, Approved Building Permits, "
    "Property Assessment FY2026, and SAM addresses"
)


@dataclass(frozen=True)
class CategoryCount:
    category: str
    label: str
    violations: int
    complaints: int
    open: int

    @property
    def total(self) -> int:
        return self.violations + self.complaints


@dataclass(frozen=True)
class HistoryRecord:
    date: str | None
    category_label: str
    kind: str  # "violation" or "complaint"
    description: str
    status: str | None
    source: str


@dataclass(frozen=True)
class PermitSummary:
    kind: str
    label: str
    count: int
    latest: str


@dataclass(frozen=True)
class BuildingHistory:
    match: AddressMatch
    building: PropertyInfo
    counts: list[CategoryCount]
    recent: list[HistoryRecord]
    permits: list[PermitSummary]
    total_records: int
    open_violations: int
    first_date: str | None
    snapshot_date: str

    @property
    def counts_by_category(self) -> dict[str, CategoryCount]:
        return {c.category: c for c in self.counts}


@dataclass(frozen=True)
class AreaStats:
    level: Literal["zip", "ward", "city"]
    area_key: str
    rental_buildings: int
    since: str
    total: int
    violations: int
    complaints: int
    by_category: dict[str, int]

    @property
    def per_100_rentals(self) -> float | None:
        if not self.rental_buildings:
            return None
        return round(self.total / self.rental_buildings * 100, 1)

    @property
    def label(self) -> str:
        if self.level == "zip":
            return f"ZIP code {self.area_key}"
        if self.level == "ward":
            return f"Ward {self.area_key}"
        return "Boston"


@dataclass(frozen=True)
class AreaContext:
    area: AreaStats
    city: AreaStats
    snapshot_date: str


@dataclass(frozen=True)
class BuildingContext:
    kind: Literal["building", "area", "none"]
    address: str
    reason: str | None = None
    match: AddressMatch | None = None
    history: BuildingHistory | None = None
    area: AreaContext | None = None
    candidates: tuple[str, ...] = field(default_factory=tuple)


def get_boston_db() -> Path:
    """FastAPI dependency so tests can point at a fixture database."""
    return DEFAULT_DB


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _has_history(con: sqlite3.Connection) -> bool:
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {"records", "permits", "area_stats"} <= names


@lru_cache(maxsize=4)
def _snapshot(db_path: str) -> str:
    with _connect(Path(db_path)) as con:
        row = con.execute("SELECT value FROM meta WHERE key='snapshot_date'").fetchone()
    return row[0] if row else "unknown"


def building_history(match: AddressMatch, db_path: Path = DEFAULT_DB) -> BuildingHistory:
    with _connect(db_path) as con:
        rows = con.execute(
            "SELECT * FROM records WHERE parcel_id = ? ORDER BY date IS NULL, date DESC",
            (match.parcel_id,),
        ).fetchall()
        permit_rows = con.execute(
            """SELECT kind, COUNT(*) n, MAX(issued_date) latest FROM permits
               WHERE parcel_id = ? GROUP BY kind""",
            (match.parcel_id,),
        ).fetchall()

    counts = []
    for cat, (label, _topic) in CATEGORIES.items():
        cat_rows = [r for r in rows if r["category"] == cat]
        counts.append(
            CategoryCount(
                category=cat,
                label=label,
                violations=sum(r["kind"] == "violation" for r in cat_rows),
                complaints=sum(r["kind"] == "complaint" for r in cat_rows),
                open=sum(r["status"] == "Open" for r in cat_rows),
            )
        )
    recent = [
        HistoryRecord(
            date=r["date"],
            category_label=CATEGORIES[r["category"]][0],
            kind=r["kind"],
            description=r["description"],
            status=r["status"],
            source=SOURCE_NAMES.get(r["source"], r["source"]),
        )
        for r in rows[:RECENT_LIMIT]
    ]
    permits = [
        PermitSummary(kind=r["kind"], label=PERMIT_LABELS[r["kind"]], count=r["n"], latest=r["latest"])
        for r in sorted(permit_rows, key=lambda r: list(PERMIT_LABELS).index(r["kind"]))
    ]
    dates = [r["date"] for r in rows if r["date"]]
    return BuildingHistory(
        match=match,
        building=match.building,
        counts=counts,
        recent=recent,
        permits=permits,
        total_records=len(rows),
        open_violations=sum(c.open for c in counts),
        first_date=min(dates) if dates else None,
        snapshot_date=_snapshot(str(db_path)),
    )


def history_for_parcel(parcel_id: str, db_path: Path = DEFAULT_DB) -> BuildingHistory | None:
    """Building history for a parcel, for the town dashboard (no address string needed).

    Privacy rule 2: returns None unless the parcel is a likely rental. The address shown is the
    city's primary address for the parcel, read from boston.sqlite.
    """
    if not parcel_id or not Path(db_path).exists():
        return None
    with _connect(db_path) as con:
        if not _has_history(con):
            return None
        building = _property(con, parcel_id)
        if building is None or not building.is_rental:
            return None
        addr = con.execute(
            """SELECT * FROM addresses WHERE parcel_id = ?
               ORDER BY is_primary DESC, display_address LIMIT 1""",
            (parcel_id,),
        ).fetchone()
    if addr is None:
        return None
    match = AddressMatch(
        matched=True,
        match_type="exact",
        sam_id=addr["sam_id"],
        parcel_id=parcel_id,
        display_address=addr["display_address"],
        zip=addr["zip"],
        ward=addr["ward"],
        neighborhood=addr["neighborhood"],
        lat=addr["lat"],
        lon=addr["lon"],
        building=building,
    )
    return building_history(match, db_path)


def snapshot_date(db_path: Path = DEFAULT_DB) -> str | None:
    """Boston data snapshot date, or None when the database isn't available."""
    if not Path(db_path).exists():
        return None
    try:
        value = _snapshot(str(db_path))
    except sqlite3.Error:
        return None
    return None if value == "unknown" else value


def _area_row(con: sqlite3.Connection, level: str, key: str) -> AreaStats | None:
    r = con.execute(
        "SELECT * FROM area_stats WHERE level = ? AND area_key = ?", (level, key)
    ).fetchone()
    if r is None:
        return None
    return AreaStats(
        level=level,
        area_key=key,
        rental_buildings=r["rental_buildings"],
        since=r["since"],
        total=r["total"],
        violations=r["violations"],
        complaints=r["complaints"],
        by_category={cat: r[f"n_{cat}"] for cat in CATEGORIES},
    )


def area_context(zip_code: str | None, ward: int | None, db_path: Path = DEFAULT_DB) -> AreaContext | None:
    with _connect(db_path) as con:
        city = _area_row(con, "city", "Boston")
        area = None
        if zip_code:
            area = _area_row(con, "zip", zip_code)
        if area is None and ward is not None:
            area = _area_row(con, "ward", str(ward))
    if area is None or city is None:
        return None
    return AreaContext(area=area, city=city, snapshot_date=_snapshot(str(db_path)))


NOT_RENTAL_REASON = (
    "Boston's assessment records don't list this building as a rental ({why}), so building "
    "history isn't shown. Here's what's been reported nearby."
)
NO_MATCH_AREA_REASON = "{why} Here's what's been reported in the same ZIP code."


def context_for_address(address: str, db_path: Path = DEFAULT_DB) -> BuildingContext | None:
    """Building or area context for a report. None when no address was given."""
    address = (address or "").strip()
    if not address:
        return None
    match = lookup(address, db_path)

    if match.reason == "data_unavailable":
        return BuildingContext(kind="none", address=address, reason=match.reason_text, match=match)
    with _connect(db_path) as con:
        if not _has_history(con):
            return BuildingContext(
                kind="none", address=address, reason="Boston building history isn't loaded on this server.", match=match
            )

    if match.matched and match.is_rental:
        return BuildingContext(
            kind="building", address=address, match=match, history=building_history(match, db_path)
        )

    if match.matched:
        why = match.building.rental_reason if match.building else "no assessment record"
        reason = NOT_RENTAL_REASON.format(why=why)
        area = area_context(match.zip, match.ward, db_path)
    elif match.reason == "outside_boston":
        return BuildingContext(kind="none", address=address, reason=match.reason_text, match=match)
    else:
        parsed = parse_address(address)
        zip_code = parsed.zip if parsed else None
        reason = NO_MATCH_AREA_REASON.format(why=match.reason_text)
        area = area_context(zip_code, None, db_path) if zip_code else None
        if area is None:
            return BuildingContext(
                kind="none", address=address, reason=match.reason_text, match=match, candidates=match.candidates
            )

    if area is None:
        return BuildingContext(kind="none", address=address, reason=reason, match=match)
    return BuildingContext(kind="area", address=address, reason=reason, match=match, area=area)
