"""The app's own database: tenant hazard reports and town inspection statuses.

Separate from boston.sqlite, which is read-only city data.
"""

import sqlite3
from pathlib import Path

from fastapi import Depends

from app.config import Settings, get_settings

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    address_input    TEXT NOT NULL,      -- as typed, trimmed
    address_key      TEXT,               -- normalized "NUMBER STREET ZIP" for grouping unmatched addresses
    display_address  TEXT,               -- Boston's official address when matched
    parcel_id        TEXT,               -- Boston building parcel when matched
    sam_id           TEXT,
    ward             INTEGER,
    zip              TEXT,
    category         TEXT NOT NULL,      -- most serious problem selected (used for scoring)
    extra_categories TEXT,               -- other problems selected, comma-separated ids
    description      TEXT,               -- emails and phone numbers removed
    observed_date    TEXT,               -- YYYY-MM-DD, optional
    -- Day precision only, so a report can't be matched to a timestamped log line.
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d', 'now')),
    is_simulated     INTEGER NOT NULL DEFAULT 0 CHECK (is_simulated IN (0, 1)),
    status           TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'scheduled', 'inspected'))
);
CREATE INDEX IF NOT EXISTS idx_reports_parcel ON reports (is_simulated, parcel_id);
CREATE INDEX IF NOT EXISTS idx_reports_key ON reports (is_simulated, address_key);

-- Simulated tenant reports for the demo, kept in their own table so they can never mix with
-- real reports. Masked by design: there are no address, parcel, SAM ID, or ZIP columns, so a
-- simulated row can't be tied to a real building. Only ward and rental type are stored.
CREATE TABLE IF NOT EXISTS simulated_reports (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    sim_building     TEXT NOT NULL,      -- synthetic group ID, e.g. "SIM-07"
    ward             INTEGER NOT NULL,
    rental_type      TEXT NOT NULL,      -- e.g. "3-family", "apartment building"
    category         TEXT NOT NULL,
    description      TEXT,               -- fictional
    observed_date    TEXT,               -- YYYY-MM-DD
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_sim_building ON simulated_reports (sim_building);

-- Town dashboard inspection status, one row per real building (ranking building_key).
-- Workflow only: never a ranking input. Day precision.
CREATE TABLE IF NOT EXISTS building_status (
    building_key TEXT PRIMARY KEY,
    status       TEXT NOT NULL CHECK (status IN ('open', 'scheduled', 'inspected')),
    updated_on   TEXT NOT NULL           -- YYYY-MM-DD
);

-- Town dashboard sessions that were signed out before they expired. The nonce is random and
-- not personal data. Rows are pruned once expires_at (Unix seconds) has passed.
CREATE TABLE IF NOT EXISTS revoked_sessions (
    nonce      TEXT PRIMARY KEY,
    expires_at INTEGER NOT NULL
);
"""


def db_path(settings: Settings) -> Path:
    p = Path(settings.app_db_path)
    return p if p.is_absolute() else ROOT / p


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.executescript(SCHEMA)
        # Additive migrations for databases created before a column existed.
        cols = {r[1] for r in con.execute("PRAGMA table_info(reports)")}
        if "extra_categories" not in cols:
            try:
                con.execute("ALTER TABLE reports ADD COLUMN extra_categories TEXT")
            except sqlite3.OperationalError as exc:
                # Another process added it first.
                if "duplicate column" not in str(exc).lower():
                    raise


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


_initialized: set[Path] = set()


def get_app_db(settings: Settings = Depends(get_settings)) -> Path:
    """FastAPI dependency: path to the app database, with the schema applied once per process.

    Runs the (idempotent) schema even if the file exists, since an empty file can appear
    if something else opened the path first.
    """
    path = db_path(settings)
    # Re-apply the schema if the file was deleted while the server was running.
    if path not in _initialized or not path.exists():
        init_db(path)
        _initialized.add(path)
    return path
