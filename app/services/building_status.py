"""Town inspection status per real building: open -> scheduled -> inspected.

Workflow only. Status is never read by the ranking service and never changes scores.
"""
from contextlib import closing
from datetime import date
from pathlib import Path

from app.db import connect

STATUSES = ("open", "scheduled", "inspected")
STATUS_LABELS = {"open": "Open", "scheduled": "Inspection scheduled", "inspected": "Inspected"}
DEFAULT_STATUS = "open"


def get_statuses(app_db: Path, keys: list[str] | None = None) -> dict[str, dict]:
    """building_key -> {"status", "updated_on"}. All rows when keys is None."""
    with closing(connect(app_db)) as con:
        if keys is None:
            rows = con.execute("SELECT building_key, status, updated_on FROM building_status").fetchall()
        else:
            rows = []
            for i in range(0, len(keys), 500):
                chunk = keys[i : i + 500]
                marks = ",".join("?" * len(chunk))
                rows += con.execute(
                    f"SELECT building_key, status, updated_on FROM building_status WHERE building_key IN ({marks})",
                    chunk,
                ).fetchall()
    return {r["building_key"]: {"status": r["status"], "updated_on": r["updated_on"]} for r in rows}


def get_status(app_db: Path, key: str) -> dict:
    return get_statuses(app_db, [key]).get(key, {"status": DEFAULT_STATUS, "updated_on": None})


def set_status(app_db: Path, key: str, status: str, today: date | None = None) -> dict:
    if status not in STATUSES:
        raise ValueError("unknown status")
    updated = (today or date.today()).isoformat()
    with closing(connect(app_db)) as con, con:
        con.execute(
            """INSERT INTO building_status (building_key, status, updated_on) VALUES (?, ?, ?)
               ON CONFLICT(building_key) DO UPDATE SET status = excluded.status, updated_on = excluded.updated_on""",
            (key, status, updated),
        )
    return {"status": status, "updated_on": updated}
