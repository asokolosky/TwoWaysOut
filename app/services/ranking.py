"""Rank buildings by reported fire-safety problems, for the town dashboard.

    rank_real_buildings(app_db, boston_db)  -> real tenant reports + Boston official records
    rank_simulated(app_db)                  -> masked simulated reports, ranked on their own
    building_reports(app_db, building_key)  -> real reports for one building (detail page)

Scoring:
    tenant score   = sum of severity x 0.5 ** (age_days / HALF_LIFE_DAYS) over real reports
    official score = min(OFFICIAL_CAP, 3 x open fire-related violations
                         + 1 x fire-related records in the 12 months before the Boston snapshot)
    total          = tenant + official (both parts are always returned so they can be shown)

Building age, ZIP/neighborhood, and demographics are deliberately excluded from scoring.
They are never read here as score inputs; ZIP and ward are used only for display and for the
dashboard's ZIP filter. Rankings reflect reported problems, not predicted fire risk.

Privacy:
    - Real ranking reads only `reports WHERE is_simulated = 0` and never touches
      `simulated_reports`. Simulated rankings read only `simulated_reports`.
    - Official history is only used for likely rentals (`properties.is_rental = 1`). A matched
      parcel that isn't a likely rental can appear from tenant reports, with official score 0,
      no parcel ID, and a normalized building-level address instead of the city's address.
    - The tenant-typed `address_input` is never displayed. Buildings without a Boston address
      show a building-level address built from the normalized key (unit numbers dropped), or
      "Address not recognized".
    - Dates are read at day precision only (first 10 characters).
"""

import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.content.report_categories import REPORT_CATEGORIES
from app.services.address_normalize import display_from_key
from app.services.fire_categories import CATEGORIES as FIRE_CATEGORIES
from app.services.reports import split_categories, text_key

HALF_LIFE_DAYS = 90
OFFICIAL_CAP = 10
OPEN_VIOLATION_POINTS = 3
RECENT_RECORD_POINTS = 1
RECENT_WINDOW_YEARS = 1
TOP_HAZARDS = 3
UNRECOGNIZED_ADDRESS = "Address not recognized"
_CHUNK = 500  # SQLite parameter batches


@dataclass(frozen=True)
class RankedBuilding:
    rank: int
    building_key: str
    parcel_id: str | None
    display_address: str
    zip: str | None
    ward: int | None
    is_boston_rental: bool
    rental_type_label: str | None
    tenant_score: float
    official_score: int
    total_score: float
    report_count: int
    open_violations: int
    recent_official_records: int
    top_hazards: tuple[str, ...]
    latest_activity: str | None


@dataclass(frozen=True)
class SimulatedBuilding:
    """A masked, synthetic building. There are no address, parcel, or ZIP fields on purpose."""

    rank: int
    sim_building: str
    label: str
    ward: int
    rental_type: str
    tenant_score: float
    report_count: int
    top_hazards: tuple[str, ...]
    latest_activity: str | None
    is_simulated: bool = True


@dataclass(frozen=True)
class BuildingReport:
    category: str  # most serious problem selected
    category_label: str
    categories: tuple[str, ...]  # every problem selected, most serious first
    category_labels: tuple[str, ...]
    description: str | None
    observed_date: str | None  # YYYY-MM-DD
    created_at: str  # YYYY-MM-DD
    status: str
    observed_month: str | None  # YYYY-MM, for month-level display
    created_month: str  # YYYY-MM


# --- Scoring helpers ----------------------------------------------------------------------


def _category(cat_id: str):
    return REPORT_CATEGORIES.get(cat_id, REPORT_CATEGORIES["other"])


def decay(age_days: int) -> float:
    return 0.5 ** (max(age_days, 0) / HALF_LIFE_DAYS)


def report_weight(category: str, observed_date: str | None, created_at: str, as_of: date) -> float:
    """Severity x recency decay. Reports dated in the future count at full weight."""
    when = date.fromisoformat(_day(observed_date) or _day(created_at))
    return _category(category).severity * decay((as_of - when).days)


def official_score(open_violations: int, recent_records: int) -> int:
    return min(OFFICIAL_CAP, OPEN_VIOLATION_POINTS * open_violations + RECENT_RECORD_POINTS * recent_records)


def _top(contrib: dict[str, float]) -> tuple[str, ...]:
    ranked = sorted((c for c in contrib.items() if c[1] > 0), key=lambda kv: (-kv[1], kv[0]))
    return tuple(label for label, _ in ranked[:TOP_HAZARDS])


def _day(value: str | None) -> str | None:
    """Day precision only: "2026-10-24 13:05:00" -> "2026-10-24"."""
    return value[:10] if value else None


def _month(value: str | None) -> str | None:
    return value[:7] if value else None


def _latest(*dates: str | None) -> str | None:
    present = [_day(d) for d in dates if d]
    return max(present) if present else None


def _sort_and_rank(items: list[dict], score_key: str, name_key: str) -> list[dict]:
    # Stable sorts, least significant key first: name asc (then key, so identical display
    # names order deterministically), latest desc (None last), score desc.
    items.sort(key=lambda b: (b[name_key], b.get("building_key", "")))
    items.sort(key=lambda b: b["latest_activity"] or "", reverse=True)
    if score_key == "total_score":
        items.sort(key=lambda b: b["tenant_score"], reverse=True)
    items.sort(key=lambda b: b[score_key], reverse=True)
    return items


# --- Database access ----------------------------------------------------------------------


def _ro(path: Path) -> sqlite3.Connection | None:
    if not Path(path).exists():
        return None
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _chunks(items: list[str]):
    for i in range(0, len(items), _CHUNK):
        yield items[i : i + _CHUNK]


def building_key_for(row) -> str:
    """Grouping key for a report row. Never contains raw typed text.

    Saved reports always have address_key. Older rows without one get the same normalized
    key save_report would have used (unit numbers dropped); if the address can't be parsed,
    the report gets its own opaque "UNKEYED <id>" key.
    """
    if row["address_key"]:
        return row["address_key"]
    if row["parcel_id"]:
        return f"PARCEL {row['parcel_id']}"
    return text_key(row["address_input"] or "") or f"UNKEYED {row['id']}"


def _text_display(key: str, reports: list[sqlite3.Row]) -> str:
    """Building-level address from normalized keys, for buildings without a city address."""
    if not key.startswith(("PARCEL ", "UNKEYED ")):
        return display_from_key(key)
    # Parcel-keyed reports: rebuild the normalized key from the newest parseable report.
    for r in reversed(reports):
        k = text_key(r["address_input"] or "")
        if k:
            return display_from_key(k)
    return UNRECOGNIZED_ADDRESS


_REPORT_COLUMNS = """id, address_key, address_input, parcel_id, ward, zip, category, extra_categories,
                     description, observed_date, created_at, status"""


def _report_columns(con: sqlite3.Connection) -> str:
    """Report columns, tolerating databases created before extra_categories existed
    (ranking opens the app DB read-only, so it can't migrate it)."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(reports)")}
    if "extra_categories" in cols:
        return _REPORT_COLUMNS
    return _REPORT_COLUMNS.replace("extra_categories", "NULL AS extra_categories")


def _all_categories(row) -> list[str]:
    """Every problem type on a report, scored one first. Older rows have no extra_categories."""
    extra = row["extra_categories"] if "extra_categories" in row.keys() else None
    return split_categories(row["category"], extra)


def _real_reports(app_db: Path) -> list[sqlite3.Row]:
    con = _ro(app_db)
    if con is None:
        return []
    with closing(con):
        if "reports" not in _tables(con):
            return []
        # Real reports only, filtered in SQL. simulated_reports is never read here.
        rows = con.execute(
            f"SELECT {_report_columns(con)} FROM reports WHERE is_simulated = 0 ORDER BY SUBSTR(created_at, 1, 10), id"
        ).fetchall()
    return rows


def _snapshot_window(con: sqlite3.Connection) -> tuple[str, str] | None:
    if "meta" not in _tables(con):
        return None
    row = con.execute("SELECT value FROM meta WHERE key = 'snapshot_date'").fetchone()
    if not row:
        return None
    end = date.fromisoformat(row[0])
    try:
        start = end.replace(year=end.year - RECENT_WINDOW_YEARS)
    except ValueError:  # Feb 29
        start = end.replace(year=end.year - RECENT_WINDOW_YEARS, day=28)
    return start.isoformat(), end.isoformat()


@dataclass
class _Official:
    open_violations: int = 0
    recent: int = 0
    latest: str | None = None
    # fire category -> (open, recent), for hazard labels and the category filter
    by_category: dict[str, tuple[int, int]] | None = None


def _official_by_parcel(con: sqlite3.Connection, tables: set[str]) -> dict[str, _Official]:
    """One aggregate query over fire-related records at likely-rental parcels."""
    if not {"records", "properties"} <= tables:
        return {}
    window = _snapshot_window(con)
    if window is None:
        return {}
    start, end = window
    rows = con.execute(
        """SELECT r.parcel_id, r.category,
                  SUM(r.kind = 'violation' AND r.status = 'Open') AS open_v,
                  SUM(r.date >= ? AND r.date <= ?) AS recent,
                  MAX(r.date) AS latest
           FROM records r
           JOIN properties p ON p.parcel_id = r.parcel_id AND p.is_rental = 1
           GROUP BY r.parcel_id, r.category""",
        (start, end),
    ).fetchall()
    out: dict[str, _Official] = {}
    for r in rows:
        o = out.setdefault(r["parcel_id"], _Official(by_category={}))
        o.open_violations += r["open_v"] or 0
        o.recent += r["recent"] or 0
        o.latest = _latest(o.latest, r["latest"])
        o.by_category[r["category"]] = (r["open_v"] or 0, r["recent"] or 0)
    return out


def _parcel_info(con: sqlite3.Connection, tables: set[str], parcels: list[str]) -> tuple[dict, dict]:
    """Primary address and property row for each parcel (batched IN queries)."""
    addrs: dict[str, sqlite3.Row] = {}
    props: dict[str, sqlite3.Row] = {}
    for chunk in _chunks(parcels):
        marks = ",".join("?" * len(chunk))
        if "addresses" in tables:
            for r in con.execute(
                f"""SELECT parcel_id, display_address, zip, ward, neighborhood FROM addresses
                    WHERE parcel_id IN ({marks})
                    ORDER BY parcel_id, is_primary DESC, display_address""",
                chunk,
            ):
                addrs.setdefault(r["parcel_id"], r)
        if "properties" in tables:
            for r in con.execute(
                f"SELECT parcel_id, land_use_desc, is_rental FROM properties WHERE parcel_id IN ({marks})",
                chunk,
            ):
                props[r["parcel_id"]] = r
    return addrs, props


def _format_address(addr: sqlite3.Row) -> str:
    place = " ".join(x for x in (addr["neighborhood"], addr["zip"]) if x)
    return f"{addr['display_address']}, {place}" if place else addr["display_address"]


def _matches_category(category: str, tenant_cats: set[str], official: _Official | None) -> bool:
    """`category` may be a report category id (e.g. "smoke_alarm") or a fire category
    (e.g. "egress"), which also matches tenant reports linked to it and official records."""
    if category in tenant_cats:
        return True
    if category in FIRE_CATEGORIES:
        if any(_category(c).fire_category == category for c in tenant_cats):
            return True
        if official and official.by_category and any(official.by_category.get(category, (0, 0))):
            return True
    return False


# --- Public API ---------------------------------------------------------------------------


def rank_real_buildings(
    app_db: Path,
    boston_db: Path,
    as_of: date | None = None,
    limit: int | None = None,
    zip_code: str | None = None,
    category: str | None = None,
) -> list[RankedBuilding]:
    as_of = as_of or date.today()

    # Tenant side: real reports grouped by building.
    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in _real_reports(app_db):
        groups[building_key_for(r)].append(r)

    # Official side: Boston records (rental parcels only).
    official: dict[str, _Official] = {}
    addrs: dict = {}
    props: dict = {}
    con = _ro(boston_db)
    if con is not None:
        with closing(con):
            tables = _tables(con)
            official = _official_by_parcel(con, tables)
            official = {
                p: o for p, o in official.items() if official_score(o.open_violations, o.recent) > 0
                or f"PARCEL {p}" in groups
            }
            report_parcels = {r["parcel_id"] for rows in groups.values() for r in rows if r["parcel_id"]}
            addrs, props = _parcel_info(con, tables, sorted(report_parcels | set(official)))

    keys = set(groups) | {f"PARCEL {p}" for p in official}
    items: list[dict] = []
    for key in keys:
        reports = groups.get(key, [])
        parcel = next((r["parcel_id"] for r in reports if r["parcel_id"]), None)
        if parcel is None and key.startswith("PARCEL "):
            parcel = key.removeprefix("PARCEL ")
        prop = props.get(parcel) if parcel else None
        is_rental = bool(prop and prop["is_rental"] == 1)
        # Privacy rule 2: no official history for parcels that aren't likely rentals.
        off = official.get(parcel) if parcel and is_rental else None

        contrib: dict[str, float] = defaultdict(float)
        tenant = 0.0
        for r in reports:
            # One submission counts once, at its most serious problem (stored in `category`).
            w = report_weight(r["category"], r["observed_date"], r["created_at"], as_of)
            tenant += w
            # Hazard labels credit every selected problem, weighted by its own severity.
            for c in _all_categories(r):
                contrib[_category(c).label] += report_weight(c, r["observed_date"], r["created_at"], as_of)
        open_v = off.open_violations if off else 0
        recent = off.recent if off else 0
        o_score = official_score(open_v, recent)
        if off and off.by_category:
            for cat, (o, rc) in off.by_category.items():
                contrib[FIRE_CATEGORIES[cat][0]] += OPEN_VIOLATION_POINTS * o + RECENT_RECORD_POINTS * rc

        latest_report = reports[-1] if reports else None
        # Privacy rule 2: city address data only for likely rentals.
        addr = addrs.get(parcel) if parcel and is_rental else None
        if addr is not None:
            display, zip_, ward = _format_address(addr), addr["zip"], addr["ward"]
        else:
            # Never the typed address_input: a normalized building-level address instead.
            display = _text_display(key, reports)
            # ZIP/ward are area-level context saved with the report.
            zip_ = latest_report["zip"] if latest_report else None
            ward = latest_report["ward"] if latest_report else None

        if zip_code and zip_ != zip_code:
            continue
        if category and not _matches_category(category, {c for r in reports for c in _all_categories(r)}, off):
            continue

        items.append(
            {
                "building_key": key,
                "parcel_id": parcel if is_rental else None,
                "display_address": display,
                "zip": zip_,
                "ward": ward,
                "is_boston_rental": is_rental,
                "rental_type_label": prop["land_use_desc"] if is_rental else None,
                "tenant_score": tenant,
                "official_score": o_score,
                "total_score": tenant + o_score,
                "report_count": len(reports),
                "open_violations": open_v,
                "recent_official_records": recent,
                "top_hazards": _top(contrib),
                "latest_activity": _latest(
                    *(d for r in reports for d in (r["observed_date"], r["created_at"])),
                    off.latest if off else None,
                ),
            }
        )

    _sort_and_rank(items, "total_score", "display_address")
    if limit is not None:
        items = items[:limit]
    return [RankedBuilding(rank=i, **b) for i, b in enumerate(items, start=1)]


def rank_simulated(app_db: Path, as_of: date | None = None) -> list[SimulatedBuilding]:
    """Masked simulated buildings, ranked only against each other. Never mixed with real ones."""
    as_of = as_of or date.today()
    con = _ro(app_db)
    if con is None:
        return []
    with closing(con):
        if "simulated_reports" not in _tables(con):
            return []
        rows = con.execute(
            """SELECT sim_building, ward, rental_type, category, observed_date, created_at
               FROM simulated_reports ORDER BY created_at, id"""
        ).fetchall()

    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        groups[r["sim_building"]].append(r)
    items = []
    for sim, reports in groups.items():
        contrib: dict[str, float] = defaultdict(float)
        score = 0.0
        for r in reports:
            w = report_weight(r["category"], r["observed_date"], r["created_at"], as_of)
            score += w
            contrib[_category(r["category"]).label] += w
        first = reports[0]
        items.append(
            {
                "sim_building": sim,
                "label": f"Simulated report · Ward {first['ward']} · {first['rental_type']}",
                "ward": first["ward"],
                "rental_type": first["rental_type"],
                "tenant_score": score,
                "report_count": len(reports),
                "top_hazards": _top(contrib),
                "latest_activity": _latest(*(d for r in reports for d in (r["observed_date"], r["created_at"]))),
            }
        )
    _sort_and_rank(items, "tenant_score", "sim_building")
    return [SimulatedBuilding(rank=i, **b) for i, b in enumerate(items, start=1)]


def building_reports(app_db: Path, building_key: str) -> list[BuildingReport]:
    """Real (non-simulated) reports for one building, newest first."""
    con = _ro(app_db)
    if con is None:
        return []
    with closing(con):
        if "reports" not in _tables(con):
            return []
        # Rows without a stored key are keyed in Python, the same way the ranking does.
        rows = con.execute(
            f"""SELECT {_report_columns(con)} FROM reports
                WHERE is_simulated = 0 AND (address_key = ? OR address_key IS NULL)""",
            (building_key,),
        ).fetchall()
    rows = [r for r in rows if building_key_for(r) == building_key]
    rows.sort(key=lambda r: (_day(r["observed_date"]) or _day(r["created_at"]), r["id"]), reverse=True)
    return [
        BuildingReport(
            category=r["category"],
            category_label=_category(r["category"]).label,
            categories=tuple(_all_categories(r)),
            category_labels=tuple(_category(c).label for c in _all_categories(r)),
            description=r["description"],
            observed_date=_day(r["observed_date"]),
            created_at=_day(r["created_at"]),
            status=r["status"],
            observed_month=_month(r["observed_date"]),
            created_month=_month(r["created_at"]),
        )
        for r in rows
    ]
