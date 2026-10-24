"""Look up a Boston address from the command line.

Usage:
    python -m scripts.lookup "182 London St 02128"
"""

import sys

from app.services.address import lookup


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit('Usage: python -m scripts.lookup "182 London St 02128"')
    m = lookup(" ".join(sys.argv[1:]))
    if not m.matched:
        print(f"No match: {m.reason_text}")
        if m.candidates:
            print("Possible ZIP codes:", ", ".join(m.candidates))
        return
    print(f"Matched ({m.match_type}): {m.display_address}, {m.neighborhood} {m.zip}")
    print(f"  SAM ID {m.sam_id} · parcel {m.parcel_id} · ward {m.ward}")
    p = m.building
    if p is None:
        print("  No assessment record for this parcel.")
        return
    print(f"  {p.land_use_desc} ({p.land_use}), units: {p.units if p.units is not None else 'n/a'}")
    print(f"  Rental: {'yes' if p.is_rental else 'no'} ({p.rental_reason})")
    print(f"  Year built: {p.year_built or 'n/a'}  Remodeled: {p.year_remodeled or 'n/a'}  Heat: {p.heat_type or 'n/a'}")


if __name__ == "__main__":
    main()
