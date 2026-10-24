"""Print the building ranking from the command line.

Usage:
    python -m scripts.rank [--limit 10]

Real buildings (real tenant reports + Boston official records) come first. Simulated reports
are printed separately, masked, and never mixed into the real ranking.

Only building-level addresses are printed (Boston's address for likely rentals, otherwise the
normalized key such as "12 Example St 01002", or "Address not recognized"). The address a
tenant typed is never printed.
"""

import argparse

from app.config import get_settings
from app.content.copy import RANKING_STATEMENT
from app.db import db_path
from app.services.address import DEFAULT_DB
from app.services.ranking import rank_real_buildings, rank_simulated


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank buildings by reported fire-safety problems.")
    parser.add_argument("--limit", type=int, default=10, help="how many buildings to show (default 10)")
    args = parser.parse_args()

    app_db = db_path(get_settings())
    real = rank_real_buildings(app_db, DEFAULT_DB, limit=args.limit)
    print(RANKING_STATEMENT)
    print()
    print(f"REAL BUILDINGS (top {args.limit})")
    print(f"{'#':>3}  {'Tenant':>6}  {'Official':>8}  {'Total':>6}  Address / hazards")
    for b in real:
        print(f"{b.rank:>3}  {b.tenant_score:>6.2f}  {b.official_score:>8}  {b.total_score:>6.2f}  {b.display_address}")
        detail = f"{b.report_count} tenant report(s), {b.open_violations} open violation(s), {b.recent_official_records} record(s) in last 12 months"
        print(f"{'':>32}{detail}")
        if b.top_hazards:
            print(f"{'':>32}Hazards: {', '.join(b.top_hazards)}")
    if not real:
        print("  (none)")

    sim = rank_simulated(app_db)
    print()
    print(f"SIMULATED (masked) - demo data, not real buildings, not part of the ranking above ({len(sim)} groups)")
    for s in sim[: args.limit]:
        hazards = ", ".join(s.top_hazards)
        print(f"{s.rank:>3}  {s.tenant_score:>6.2f}  {s.sim_building}  {s.label}  ({s.report_count} reports: {hazards})")
    if not sim:
        print("  (none)")


if __name__ == "__main__":
    main()
