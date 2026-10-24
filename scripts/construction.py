"""Nearby construction from Boston's approved building permits (block level only).

Privacy (project rule 8): only whitelisted columns are read. `applicant`, `comments`,
`description`, and `total_fees` are never loaded. `declared_valuation` is read only to filter
out small jobs and is never stored. The exact house number and full address are never stored:
each site gets a block label ("100 block of Main St"). The parcel ID is kept only so the app can
leave out the matched building's own permits (that's building history, rule 2).

Classification, from the permits issued in the 24 months before the snapshot:
    new_construction  permit type "Erect/New Construction" or "Foundation Permit", or worktype ERECT
    major_work        "Long Form/Alteration Permit" with a structural worktype (addition,
                      interior/exterior renovation, change of building) and a declared value of
                      at least MAJOR_WORK_MIN_VALUE; or a RAZE (full demolition) permit of any type
"""

import re

import pandas as pd

from app.services.address_normalize import SUFFIXES, display_from_key, street_key
from scripts.history import _pid, _to_building

CONSTRUCTION_COLUMNS = [
    "permitnumber", "worktype", "permittypedescr", "declared_valuation", "issued_date", "status",
    "address", "property_id", "parcel_id", "y_latitude", "x_longitude",
]

NEW_CONSTRUCTION_TYPES = {"Erect/New Construction", "Foundation Permit"}
LONG_FORM = "Long Form/Alteration Permit"
STRUCTURAL_WORKTYPES = {"ADDITION", "INTEXT", "INTREN", "EXTREN", "COB"}
# Full demolition. Partial demolition (INTDEM, EXTDEM) is filed on short forms for small jobs
# (median declared value about $12,000 in 2024-2026), so it's left out.
DEMOLITION_WORKTYPES = {"RAZE"}
# Long-form structural permits in 2024-2026 have a median declared value of $150,000 to
# $240,000, and a lower quartile of $23,000 to $80,000 (kitchens, porches, small repairs).
# $100,000 keeps about 60% of them: the larger jobs that bring crews, heaters, and hot work.
MAJOR_WORK_MIN_VALUE = 100_000
WINDOW_MONTHS = 24

WORK_LABELS = {
    "ERECT": "New building",
    "FOUNDATION": "Foundation for a new building",
    "ADDITION": "Addition to a building",
    "INTEXT": "Major interior and exterior renovation",
    "INTREN": "Major interior renovation",
    "EXTREN": "Major exterior renovation",
    "COB": "Major renovation (change of building)",
    "RAZE": "Demolition",
}
KIND_RANK = {"new_construction": 0, "major_work": 1}

_NUMBER = re.compile(r"^\s*(\d+)[A-Z]?(?:\s*-\s*\d+[A-Z]?)?\s+(.+)$", re.IGNORECASE)
_ORDINAL = re.compile(r"^\d+(ST|ND|RD|TH)$")
_JOINERS = {"&", "AND", "TO", "THRU", "THROUGH", "REAR", "FRONT"}
_UNIT_WORDS = {"UNIT", "APT", "APARTMENT", "STE", "SUITE", "FL", "FLR", "FLOOR", "BSMT", "BASEMENT", "REAR", "FRONT", "RM", "ROOM"}
_UNIT_WORDS |= {"BLDG", "BUILDING", "PH", "PENTHOUSE", "LOWER", "UPPER", "NO", "NUMBER", "LOT", "GARAGE", "PARKING", "STORE"}
_DIRECTIONS = {"N", "S", "E", "W"}
# The label must end in a street suffix (optionally followed by a direction). Anything after the
# suffix ("Main St B", "Main St Dorchester") could be a unit or place, so it's refused.
# Boston's permits use two-letter codes for some suffixes (TE, WY, PK, ...), found in the data.
_BOSTON_SUFFIX_CODES = {"TE", "WY", "PK", "PZ", "WH", "CI", "BL", "HW", "CR", "PW", "CC", "MA", "EX"}
_STREET_END = set(SUFFIXES) | set(SUFFIXES.values()) | _BOSTON_SUFFIX_CODES
_ALLOWED_CHARS = re.compile(r"^[A-Za-z0-9 .'\-]+$")


def block_label(address: str | None) -> str | None:
    """'31-33 Boardman ST' -> '1-99 block of Boardman St'; '182 London ST' -> '100 block of London St'.

    Never returns the house number itself.
    """
    # Allowlist, not cleanup: letters, digits, spaces, and . ' - only. This refuses fractions
    # ("12 1/2"), "#", parentheses, colons, and commas, any of which could carry a unit or place.
    if not isinstance(address, str) or not _ALLOWED_CHARS.match(address.strip() or "x/"):
        return None
    m = _NUMBER.match(address)
    if not m:
        return None
    rest = m.group(2).upper().replace(".", "").split()
    if not rest:
        return None
    end = rest[-2] if len(rest) > 2 and rest[-1] in _DIRECTIONS | {"NORTH", "SOUTH", "EAST", "WEST"} else rest[-1]
    if len(rest) < 2 or end not in _STREET_END:
        return None
    # Anything that isn't a plain street name is refused rather than cleaned up: a second
    # number ("12 14 Main"), a joiner ("12 & 14", "12 to 14"), or unit text ("Unit B", "2nd Fl").
    if not rest or not (rest[0][0].isalpha() or _ORDINAL.match(rest[0])) or rest[0] in _JOINERS:
        return None
    if any(w in _UNIT_WORDS for w in rest):
        return None
    if any(any(c.isdigit() for c in w) and not _ORDINAL.match(w) for w in rest):
        return None
    if len(rest[0]) == 1 and rest[0] not in _DIRECTIONS and len(rest) > 2:
        return None  # "12 A Main St": a unit letter, not a street named A
    street = display_from_key(street_key(m.group(2)))
    if not street or any(c.isdigit() for c in street.split()[-1]):
        return None
    hundred = int(m.group(1)) // 100 * 100
    block = "1-99" if hundred == 0 else str(hundred)
    return f"{block} block of {street}"


def _value(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype("string").str.replace(r"[$,\s]", "", regex=True), errors="coerce")


def classify(permittype: str | None, worktype: str | None, value: float | None) -> tuple[str, str] | None:
    """(kind, work label) for a permit, or None when it isn't new construction or major work."""
    if permittype in NEW_CONSTRUCTION_TYPES or worktype == "ERECT":
        label = WORK_LABELS["FOUNDATION"] if permittype == "Foundation Permit" else WORK_LABELS["ERECT"]
        return "new_construction", label
    if worktype in DEMOLITION_WORKTYPES:
        return "major_work", WORK_LABELS[worktype]
    if (
        permittype == LONG_FORM
        and worktype in STRUCTURAL_WORKTYPES
        and value is not None
        and not pd.isna(value)
        and value >= MAJOR_WORK_MIN_VALUE
    ):
        return "major_work", WORK_LABELS[worktype]
    return None


def build_construction(permits: pd.DataFrame, pmap: pd.Series, smap: pd.Series, snapshot: str) -> pd.DataFrame:
    """One row per construction site (building parcel) issued in the last 24 months."""
    p = permits[CONSTRUCTION_COLUMNS].copy()
    issued = pd.to_datetime(p["issued_date"], errors="coerce", utc=True, format="mixed")
    end = pd.Timestamp(snapshot, tz="UTC") + pd.Timedelta(days=1)
    start = end - pd.DateOffset(months=WINDOW_MONTHS)
    p = p[(issued >= start) & (issued < end)].assign(issued=issued)

    value = _value(p["declared_valuation"])
    labels = [
        classify(t, w, v)
        for t, w, v in zip(p["permittypedescr"], p["worktype"], value, strict=True)
    ]
    keep = pd.Series([lab is not None for lab in labels], index=p.index)
    p = p[keep].copy()
    p["kind"] = [lab[0] for lab in labels if lab is not None]
    p["work_label"] = [lab[1] for lab in labels if lab is not None]

    parcel = _pid(p["parcel_id"]).where(p["parcel_id"].notna() & (p["parcel_id"] != "0"))
    parcel = parcel.fillna(p["property_id"].astype("string").str.replace(r"\.0$", "", regex=True).map(smap))
    p["parcel"] = _to_building(parcel, pmap) if len(parcel) else parcel

    out = pd.DataFrame(
        {
            "parcel_id": p["parcel"],
            "lat": pd.to_numeric(p["y_latitude"], errors="coerce"),
            "lon": pd.to_numeric(p["x_longitude"], errors="coerce"),
            "block_label": p["address"].map(block_label),
            "kind": p["kind"],
            "work_label": p["work_label"],
            "issued_month": p["issued"].dt.strftime("%Y-%m"),
            "status": p["status"],
            "_issued": p["issued"],
        }
    )
    # Valid Boston coordinates and a block label are needed to show a site at all.
    out = out[
        out["lat"].between(42.2, 42.42)
        & out["lon"].between(-71.2, -70.98)
        & out["block_label"].notna()
    ]
    # Store coordinates at about 11 m precision: enough to measure "next door" and 50 m bands,
    # not enough to pinpoint a house (privacy rule 8).
    out = out.assign(lat=out["lat"].round(4), lon=out["lon"].round(4))
    # A site often has several permits (foundation, then the building). Keep one row per site:
    # the most significant kind, then the most recent.
    point = out["lat"].astype(str) + "," + out["lon"].astype(str)
    out = out.assign(_rank=out["kind"].map(KIND_RANK), _site=out["parcel_id"].fillna(point))
    out = out.sort_values(["_site", "_rank", "_issued"], ascending=[True, True, False])
    out = out.drop_duplicates("_site").drop(columns=["_rank", "_site", "_issued"])
    return out.reset_index(drop=True)
