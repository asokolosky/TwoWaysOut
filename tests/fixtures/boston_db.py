"""Build a small boston.sqlite from the fixture CSVs, using the real preprocessing code."""

import io
import json
from pathlib import Path

import pandas as pd

from scripts import history
from scripts.preprocess_boston import (
    ASSESSMENT_COLUMNS,
    PERMIT_READ_COLUMNS,
    SAM_COLUMNS,
    build_addresses,
    build_history,
    build_properties,
    load_census,
    write_db,
)
from tests.fixtures.boston_csv import (
    ASSESSMENT_CSV,
    DATACOMMONS_JSON,
    PERMITS_CSV,
    RENTSMART_CSV,
    SAM_CSV,
    VIOLATIONS_CSV,
)

SNAPSHOT = "2026-10-24"


def _read(csv: str, cols: list[str]) -> pd.DataFrame:
    # Same whitelisted columns as the real script.
    return pd.read_csv(io.StringIO(csv), dtype=str, usecols=cols)


def build_fixture_db(path: Path, with_history: bool = True, with_census: bool = True) -> Path:
    sam = _read(SAM_CSV, SAM_COLUMNS)
    assess = _read(ASSESSMENT_CSV, ASSESSMENT_COLUMNS)
    addresses = build_addresses(sam)
    properties = build_properties(assess)
    hist = None
    if with_history:
        hist = build_history(
            sam,
            assess,
            addresses,
            properties,
            _read(RENTSMART_CSV, history.RENTSMART_COLUMNS),
            _read(VIOLATIONS_CSV, history.VIOLATION_COLUMNS),
            _read(PERMITS_CSV, PERMIT_READ_COLUMNS),
            SNAPSHOT,
        )
    if with_census:
        census_file = Path(path).with_name("datacommons.json")
        census_file.write_text(json.dumps(DATACOMMONS_JSON))
        hist = {**(hist or {}), "census_zip": load_census(census_file)}
    write_db(addresses, properties, path, SNAPSHOT, hist)
    return path
