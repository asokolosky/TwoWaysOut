"""Seed the `simulated_reports` table with fictional tenant hazard reports for the dashboard demo.

    .venv/bin/python -m scripts.seed_reports [--db PATH] [--boston-db PATH]

Masked by design: simulated buildings get synthetic IDs ("SIM-01".."SIM-14") and only a ward and
rental type. The (ward, rental type) pairs are drawn from aggregate counts of likely rentals in
boston.sqlite; no parcel or address is ever selected or stored. Only `simulated_reports` is
touched; the real `reports` table is never read or written.

Deterministic (fixed seed), and idempotent: every run deletes and re-inserts all simulated rows.
"""

import argparse
import random
import sqlite3
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from app.config import get_settings
from app.content.report_categories import REPORT_CATEGORIES
from app.db import ROOT, connect, db_path, init_db
from app.services.reports import redact_contact_info

SEED = 20261024
NUM_BUILDINGS = 14
# Reports per building: a few buildings with several reports, most with 1-3. Sums to 40.
REPORTS_PER_BUILDING = [6, 5, 5, 4, 3, 3, 3, 2, 2, 2, 2, 1, 1, 1]
DAYS_BACK = 180
MAX_CREATED_LAG_DAYS = 5
# Smallest (ward, rental_type) group of real likely rentals that may be used as a simulated label.
MIN_GROUP_SIZE = 20

DEFAULT_BOSTON_DB = ROOT / "data" / "boston.sqlite"

RENTAL_TYPES = {
    "R1": "single-family",
    "R2": "2-family",
    "R3": "3-family",
    "R4": "4-6 family",
    "A": "apartment building",
    "RC": "mixed-use building",
    "CM": "condo building",
    "CD": "condo unit",
}

# Allston/Brighton, Mission Hill, Fenway/Back Bay area.
STUDENT_WARDS = {21, 22, 10, 4, 5, 3}
STUDENT_WARD_BOOST = 25

# Used when boston.sqlite is missing: plausible (ward, rental_type, weight) combinations.
FALLBACK_COMBOS: list[tuple[int, str, int]] = [
    (21, "3-family", 40), (21, "2-family", 35), (21, "apartment building", 20), (21, "condo building", 15),
    (22, "3-family", 35), (22, "2-family", 35), (22, "apartment building", 15), (22, "condo building", 15),
    (10, "3-family", 30), (10, "2-family", 20), (10, "4-6 family", 10), (10, "mixed-use building", 5),
    (4, "apartment building", 20), (4, "condo building", 15), (4, "mixed-use building", 10),
    (5, "condo building", 15), (5, "apartment building", 15), (5, "mixed-use building", 5),
    (3, "mixed-use building", 10), (3, "apartment building", 10), (3, "condo building", 10),
    (14, "3-family", 3), (15, "3-family", 3), (7, "2-family", 3), (17, "3-family", 2), (19, "2-family", 2),
]

CATEGORY_WEIGHTS = {
    "smoke_alarm": 30,
    "no_second_exit": 22,
    "heating_hazard": 22,
    "blocked_exit": 10,
    "electrical_hazard": 10,
    "other": 6,
}
# Buildings with several reports lean harder toward high-severity problems.
HIGH_SEVERITY_WEIGHTS = {
    "smoke_alarm": 35,
    "no_second_exit": 30,
    "heating_hazard": 12,
    "blocked_exit": 12,
    "electrical_hazard": 9,
    "other": 2,
}

# Short, generic, clearly fictional text. No names, contact info, addresses, or street names.
DESCRIPTIONS: dict[str, list[str]] = {
    "no_second_exit": [
        "Simulated report: the back bedroom window is painted shut, so the only way out is the front hall.",
        "Simulated report: the basement bedroom has no window and only one door.",
        "Simulated report: the attic room's only exit is a narrow stairway through the kitchen.",
        "Simulated report: the rear exit door was nailed shut last winter.",
        "Simulated report: the bedroom window is too small to climb out of.",
    ],
    "smoke_alarm": [
        "Simulated report: smoke alarm in the hallway has been beeping for weeks and was taken down.",
        "Simulated report: there is no smoke alarm on our floor.",
        "Simulated report: the carbon monoxide alarm is missing and the furnace is gas.",
        "Simulated report: the smoke alarm has no battery and the landlord has not replaced it.",
        "Simulated report: the alarm near the kitchen was removed and never put back.",
    ],
    "blocked_exit": [
        "Simulated report: the back stairway is filled with stored furniture and boxes.",
        "Simulated report: the fire escape is blocked by bikes and trash bags.",
        "Simulated report: the rear exit door is kept locked with a padlock.",
        "Simulated report: the shared hallway is stacked with old mattresses.",
    ],
    "electrical_hazard": [
        "Simulated report: an outlet in the kitchen sparks when anything is plugged in.",
        "Simulated report: exposed wiring hangs from the ceiling in the basement.",
        "Simulated report: breakers trip several times a day and we run extension cords between rooms.",
        "Simulated report: a light switch in the bathroom is warm to the touch.",
    ],
    "heating_hazard": [
        "Simulated report: no heat for over a week and the landlord gave us space heaters.",
        "Simulated report: heat does not reach the back bedrooms, so we use the oven to warm up.",
        "Simulated report: the radiators have been cold since early winter.",
        "Simulated report: the heating system makes a burning smell when it turns on.",
    ],
    "other": [
        "Simulated report: oily rags and paint cans are stored next to the furnace.",
        "Simulated report: people regularly smoke indoors in the shared stairwell.",
        "Simulated report: the dryer vent is clogged with lint and gets very hot.",
    ],
}


def load_combos(boston_db: Path) -> tuple[list[tuple[int, str, int]], str]:
    """Aggregate (ward, rental_type, count) for likely rentals. Never selects individual parcels.

    Privacy (Rule 5): a label like "Ward 3 · 4-6 family" for a group of only one or two real
    rentals could point to a specific building, so only (ward, rental_type) groups with at least
    MIN_GROUP_SIZE likely rentals are used. The threshold is applied in SQL (per land use) and
    again in Python per (ward, rental_type) after mapping, in case two land uses ever share a
    rental type.

    FALLBACK_COMBOS weights are synthetic sampling weights, not counts from any database, so they
    are not checked against MIN_GROUP_SIZE when boston.sqlite is missing. When topping up from a
    real DB, fallback pairs that match a real group below the threshold are dropped.
    """
    if not boston_db.exists():
        return FALLBACK_COMBOS, "built-in fallback (boston.sqlite not found)"
    try:
        con = sqlite3.connect(f"file:{boston_db}?mode=ro", uri=True)
        try:
            group_sql = (
                "SELECT CAST(substr(parcel_id, 1, 2) AS INTEGER) AS ward, land_use, COUNT(*) "
                "FROM properties WHERE is_rental = 1 AND parcel_id IS NOT NULL "
                "GROUP BY ward, land_use "
            )
            rows = con.execute(group_sql + "HAVING COUNT(*) >= ?", (MIN_GROUP_SIZE,)).fetchall()
            # Keys only, to keep the synthetic top-up from landing on a small real group.
            small_rows = con.execute(group_sql + "HAVING COUNT(*) < ?", (MIN_GROUP_SIZE,)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return FALLBACK_COMBOS, "built-in fallback (boston.sqlite unreadable)"
    # Sum per (ward, rental_type) after mapping, then re-check the threshold as a guard.
    totals: Counter[tuple[int, str]] = Counter()
    for ward, lu, n in rows:
        if ward and lu in RENTAL_TYPES and n:
            totals[(int(ward), RENTAL_TYPES[lu])] += int(n)
    combos = [(w, t, n) for (w, t), n in sorted(totals.items()) if n >= MIN_GROUP_SIZE]
    small = {(int(w), RENTAL_TYPES[lu]) for w, lu, _ in small_rows if w and lu in RENTAL_TYPES}
    small -= set(totals)
    if len(combos) < NUM_BUILDINGS:
        # Too little real variety (e.g. a tiny fixture DB): top up with the synthetic fallback list,
        # skipping any pair that matches a real group below the threshold.
        seen = {(w, t) for w, t, _ in combos}
        combos += [c for c in FALLBACK_COMBOS if (c[0], c[1]) not in seen | small]
        return combos, "boston.sqlite aggregates + built-in fallback"
    return combos, "boston.sqlite aggregates"


def _pick_buildings(rng: random.Random, combos: list[tuple[int, str, int]]) -> list[tuple[int, str]]:
    """Weighted sample of distinct (ward, rental_type) pairs, boosted toward student wards."""
    pool = [(w, t, n * (STUDENT_WARD_BOOST if w in STUDENT_WARDS else 1)) for w, t, n in sorted(combos)]
    picked: list[tuple[int, str]] = []
    while len(picked) < NUM_BUILDINGS and pool:
        i = rng.choices(range(len(pool)), weights=[p[2] for p in pool])[0]
        w, t, _ = pool.pop(i)
        picked.append((w, t))
    return picked


def build_rows(combos: list[tuple[int, str, int]], today: date) -> list[dict]:
    rng = random.Random(SEED)
    buildings = _pick_buildings(rng, combos)
    counts = REPORTS_PER_BUILDING[: len(buildings)]
    rng.shuffle(counts)
    cats = list(CATEGORY_WEIGHTS)
    rows = []
    for i, ((ward, rental_type), n) in enumerate(zip(buildings, counts), start=1):
        weights = HIGH_SEVERITY_WEIGHTS if n >= 4 else CATEGORY_WEIGHTS
        for _ in range(n):
            category = rng.choices(cats, weights=[weights[c] for c in cats])[0]
            description = rng.choice(DESCRIPTIONS[category])
            observed = today - timedelta(days=rng.randint(0, DAYS_BACK))
            created = min(today, observed + timedelta(days=rng.randint(0, MAX_CREATED_LAG_DAYS)))
            rows.append(
                {
                    "sim_building": f"SIM-{i:02d}",
                    "ward": ward,
                    "rental_type": rental_type,
                    "category": category,
                    "description": description,
                    "observed_date": observed.isoformat(),
                    "created_at": created.isoformat(),
                }
            )
    for r in rows:
        assert r["category"] in REPORT_CATEGORIES, r["category"]
        cleaned, changed = redact_contact_info(r["description"])
        assert not changed and cleaned == r["description"], r["description"]
    return rows


def seed(app_db: Path, boston_db: Path = DEFAULT_BOSTON_DB, today: date | None = None) -> dict:
    """Replace all rows in simulated_reports. Returns a summary dict."""
    today = today or date.today()
    init_db(app_db)
    combos, source = load_combos(boston_db)
    rows = build_rows(combos, today)
    con = connect(app_db)
    try:
        with con:
            con.execute("DELETE FROM simulated_reports")
            con.executemany(
                "INSERT INTO simulated_reports "
                "(sim_building, ward, rental_type, category, description, observed_date, created_at) "
                "VALUES (:sim_building, :ward, :rental_type, :category, :description, :observed_date, :created_at)",
                rows,
            )
    finally:
        con.close()
    buildings: dict[str, tuple[int, str, int]] = {}
    for r in rows:
        w, t, n = buildings.get(r["sim_building"], (r["ward"], r["rental_type"], 0))
        buildings[r["sim_building"]] = (w, t, n + 1)
    dates = sorted(r["observed_date"] for r in rows)
    return {
        "rows": len(rows),
        "buildings": buildings,
        "categories": Counter(r["category"] for r in rows),
        "date_range": (dates[0], dates[-1]) if dates else (None, None),
        "source": source,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=None, help="App DB path (default from settings)")
    parser.add_argument("--boston-db", type=Path, default=DEFAULT_BOSTON_DB, help="Boston DB path")
    args = parser.parse_args(argv)
    app_db = args.db or db_path(get_settings())
    s = seed(app_db, args.boston_db)
    print(f"Seeded {s['rows']} simulated reports across {len(s['buildings'])} simulated buildings in {app_db}")
    print(f"(ward, rental type) source: {s['source']}")
    for b, (w, t, n) in sorted(s["buildings"].items()):
        print(f"  {b}: ward {w}, {t}, {n} report(s)")
    print("Per category:")
    for c, n in s["categories"].most_common():
        print(f"  {c}: {n}")
    print(f"Observed dates: {s['date_range'][0]} to {s['date_range'][1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
