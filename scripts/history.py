"""Fire-related building history and area statistics from RentSmart, ISD violations, and permits.

Privacy: only whitelisted columns are read. RentSmart's `owner`, the violations `contact_*`
columns, and the permits `applicant` and free-text `comments` are never loaded.

Tables produced:
    records     fire-related violations and complaints, rental buildings only
    permits     fire alarm, sprinkler, and electrical permits, rental buildings only
    area_stats  fire-related counts by ZIP and by ward, plus a citywide row (all buildings)
"""

import pandas as pd

from app.services.fire_categories import CATEGORIES, categorize, display_description

RENTSMART_COLUMNS = ["date", "violation_type", "description", "zip_code", "parcel"]
VIOLATION_COLUMNS = ["case_no", "status_dttm", "status", "description", "violation_zip", "ward", "sam_id"]
PERMIT_COLUMNS = ["permitnumber", "worktype", "permittypedescr", "issued_date", "status", "property_id", "parcel_id"]

RENTSMART_KIND = {
    "Housing Violations": "violation",
    "Enforcement Violations": "violation",
    "Housing Complaints": "complaint",
    "Sanitation Requests": "complaint",
    "Civic Maintenance Requests": "complaint",
    # "Building Violations" are skipped: the ISD dataset has the same cases plus open/closed status.
}

PERMIT_KINDS = {
    # (worktype or permit type) -> kind shown on the card
    "FA": "fire_alarm",
    "Electrical Fire Alarms": "fire_alarm",
    "SPRINK": "sprinkler",
    "ELECTRICAL": "electrical",
    "SRVCHG": "electrical",
}
PERMIT_LABELS = {
    "fire_alarm": "Fire alarm work",
    "sprinkler": "Sprinkler work",
    "electrical": "Electrical work",
}


def _pid(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.rstrip("_").str.replace(r"\.0$", "", regex=True).str.zfill(10)


def _date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce", utc=True, format="mixed").dt.strftime("%Y-%m-%d")


def parcel_map(assess: pd.DataFrame) -> pd.Series:
    """Every assessment PID (including condo units) -> its building parcel."""
    pid = _pid(assess["PID"])
    cm = _pid(assess["CM_ID"]).where(assess["CM_ID"].notna())
    return pd.Series(cm.fillna(pid).values, index=pid.values).groupby(level=0).first()


def sam_parcel_map(sam: pd.DataFrame) -> pd.Series:
    """Every SAM address ID (including unit rows) -> its parcel."""
    s = sam.dropna(subset=["SAM_ADDRESS_ID", "PARCEL_ID"])
    return pd.Series(_pid(s["PARCEL_ID"]).values, index=s["SAM_ADDRESS_ID"].astype("string").values).groupby(level=0).first()


def _to_building(parcels: pd.Series, pmap: pd.Series) -> pd.Series:
    return parcels.map(pmap).astype("string").fillna(parcels)


def build_records(rentsmart: pd.DataFrame, violations: pd.DataFrame, pmap: pd.Series, smap: pd.Series) -> pd.DataFrame:
    """All fire-related records citywide, with building parcel, ZIP, and ward."""
    rs = rentsmart[RENTSMART_COLUMNS].copy()
    rs = rs[rs["violation_type"].isin(RENTSMART_KIND)]
    rs["category"] = rs["description"].map(categorize)
    rs = rs.dropna(subset=["category", "parcel"])
    rs_out = pd.DataFrame(
        {
            "parcel_id": _to_building(_pid(rs["parcel"]), pmap),
            "date": _date(rs["date"]),
            "source": "rentsmart",
            "kind": rs["violation_type"].map(RENTSMART_KIND),
            "category": rs["category"],
            "description": rs["description"].map(display_description),
            "status": None,
            "zip": rs["zip_code"].astype("string").str.zfill(5),
        }
    )

    v = violations[VIOLATION_COLUMNS].copy()
    v["category"] = v["description"].map(categorize)
    v = v.dropna(subset=["category"])
    v_parcel = v["sam_id"].astype("string").map(smap)
    v = v[v_parcel.notna()]
    v_out = pd.DataFrame(
        {
            "parcel_id": _to_building(v_parcel[v_parcel.notna()], pmap),
            "date": _date(v["status_dttm"]),
            "source": "isd_violations",
            "kind": "violation",
            "category": v["category"],
            "description": v["description"].map(display_description),
            "status": v["status"],
            "zip": v["violation_zip"].astype("string").str.zfill(5),
        }
    )
    out = pd.concat([rs_out, v_out], ignore_index=True)
    # Boston parcel IDs start with the ward number.
    out["ward"] = pd.to_numeric(out["parcel_id"].str[:2], errors="coerce").astype("Int64")
    return out


def build_permits(permits: pd.DataFrame, pmap: pd.Series, smap: pd.Series) -> pd.DataFrame:
    p = permits[PERMIT_COLUMNS].copy()
    kind = p["worktype"].map(PERMIT_KINDS).fillna(p["permittypedescr"].map(PERMIT_KINDS))
    p = p[kind.notna()].assign(kind=kind[kind.notna()])
    parcel = _pid(p["parcel_id"]).where(p["parcel_id"].notna() & (p["parcel_id"] != "0"))
    parcel = parcel.fillna(p["property_id"].astype("string").str.replace(r"\.0$", "", regex=True).map(smap))
    p = p[parcel.notna()]
    return pd.DataFrame(
        {
            "parcel_id": _to_building(parcel[parcel.notna()], pmap),
            "issued_date": _date(p["issued_date"]),
            "kind": p["kind"],
            "permit_type": p["permittypedescr"],
            "status": p["status"],
        }
    ).dropna(subset=["issued_date"])


def build_area_stats(records: pd.DataFrame, properties: pd.DataFrame, addresses: pd.DataFrame, snapshot: str) -> pd.DataFrame:
    """Counts of fire-related records in the last 12 months, by ZIP, ward, and citywide."""
    end = pd.Timestamp(snapshot)
    start = (end - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
    recent = records[records["date"] >= start]

    # Rental buildings per area: parcel -> primary address ZIP; ward from the parcel ID.
    rentals = properties[properties["is_rental"] == 1][["parcel_id"]].copy()
    zip_of = addresses.sort_values("is_primary", ascending=False).drop_duplicates("parcel_id").set_index("parcel_id")["zip"]
    rentals["zip"] = rentals["parcel_id"].map(zip_of)
    rentals["ward"] = pd.to_numeric(rentals["parcel_id"].str[:2], errors="coerce").astype("Int64")

    rows = []
    for level, key_col in (("zip", "zip"), ("ward", "ward"), ("city", None)):
        groups = [("Boston", recent)] if key_col is None else recent.groupby(key_col)
        rental_counts = (
            {"Boston": len(rentals)} if key_col is None else rentals.groupby(key_col).size().to_dict()
        )
        for key, g in groups:
            row = {
                "level": level,
                "area_key": str(key),
                "rental_buildings": int(rental_counts.get(key, 0)),
                "since": start,
                "total": len(g),
                "violations": int((g["kind"] == "violation").sum()),
                "complaints": int((g["kind"] == "complaint").sum()),
                "open_violations": int((records.loc[records[key_col] == key] if key_col else records)["status"].eq("Open").sum()),
            }
            for cat in CATEGORIES:
                row[f"n_{cat}"] = int((g["category"] == cat).sum())
            rows.append(row)
    return pd.DataFrame(rows)


def rental_only(df: pd.DataFrame, properties: pd.DataFrame) -> pd.DataFrame:
    rental_parcels = set(properties.loc[properties["is_rental"] == 1, "parcel_id"])
    return df[df["parcel_id"].isin(rental_parcels)].reset_index(drop=True)
