# Design: Boston data pipeline and address matching

## Overview
The pipeline runs offline (locally or in the Docker builder stage). It downloads five Analyze
Boston CSVs, reads only whitelisted columns, and writes one read-only SQLite file,
`data/boston.sqlite`. At runtime the app never touches raw data. It parses the student's address,
matches it to a building-level SAM address and parcel, and returns building history only for
likely rentals. Everything else gets ZIP, ward, or citywide statistics, or a plain reason.

## Architecture
```
scripts/build_data.sh
  -> scripts/fetch_boston.py      data.boston.gov -> data/raw/{sam,assessment,rentsmart,violations,permits}.csv
                                  + data/raw/SNAPSHOT_DATES.json (per dataset)
                                  + data/raw/SNAPSHOT_DATE (full fetch only)
  -> scripts/fetch_datacommons.py optional, only with a Data Commons key -> data/raw/datacommons.json
                                  (failure or no key: continue without census_zip)
  -> scripts/preprocess_boston.py read_csv(usecols=whitelist)
       build_addresses(sam)            -> addresses
       build_properties(assessment)    -> properties (rental classification)
       build_history(...)  via scripts/history.py
         parcel_map, sam_parcel_map    unit PID / SAM ID -> building parcel
         build_records                 RentSmart + ISD, categorized (fire_categories.py)
         rental_only                   -> records, permits (rentals only)
         build_area_stats              -> area_stats (all buildings)
       construction.build_construction -> construction (all buildings, block level)
       load_census(datacommons.json)   -> census_zip (when the file exists)
       snapshot_for                    oldest per-dataset date
       write_db                        -> boston.sqlite.tmp -> boston.sqlite (+ meta, indexes)

Runtime (read-only, file:...?mode=ro)
  app/routers/check.py   address field, or AI-extracted address, or find_address_in_text(listing)
    -> app/services/boston.py context_for_address
         -> app/services/address.py lookup -> address_normalize.parse_address
         -> building_history (rental) | area_context (non-rental / unmatched with ZIP) | none
  app/routers/town.py    history_for_parcel (rental check), snapshot_date
  scripts/lookup.py      CLI wrapper around lookup
```

In Docker (`Dockerfile`), one `RUN` executes `scripts/build_data.sh --python python`, then
`rm -rf data/raw`. The runtime stage copies only `data/boston.sqlite`, sets it to `0444`, and
asserts `data/raw` doesn't exist. `.gitignore` and `.dockerignore` both exclude `data/raw`.

## Components and Interfaces
- `scripts/fetch_boston.py`: `DATASETS` maps five names to download URLs. `_resolve` sends a HEAD
  request with redirects disabled and strips `.com:443/` from the S3 `Location`. `download`
  streams 1 MB chunks to `<name>.csv.part`, then `replace`s it. `main` rejects unknown names,
  records today's date for each fetched dataset in `SNAPSHOT_DATES.json` (`_record_dates`), and
  writes `SNAPSHOT_DATE` only when all five datasets were fetched in the run.
- `scripts/build_data.sh`: parses `--python` and `-h`, `cd`s to the project root, runs fetch
  (all datasets), then the optional `scripts.fetch_datacommons` step when a Data Commons key is
  set (`DATACOMMONS_API_KEY_FILE`, `DATACOMMONS_API_KEY`, or `DATA_COMMONS_API_KEY`; a failure
  only prints a warning), then preprocess. `set -euo pipefail`. See
  `.kiro/specs/nearby-construction-and-census/`.
- `scripts/preprocess_boston.py`: column whitelists `SAM_COLUMNS`, `ASSESSMENT_COLUMNS`;
  `build_addresses`, `classify`, `build_properties`, `build_history`, `load_census`,
  `snapshot_for` (oldest per-dataset date, falling back to `SNAPSHOT_DATE`, then today),
  `write_db`, `main`.
- `scripts/history.py`: whitelists `RENTSMART_COLUMNS`, `VIOLATION_COLUMNS`, `PERMIT_COLUMNS`;
  `RENTSMART_KIND`, `PERMIT_KINDS`; `parcel_map`, `sam_parcel_map`, `build_records`,
  `build_permits`, `build_area_stats`, `rental_only`.
- `app/services/fire_categories.py`: `CATEGORIES` (label and related checklist topic), `EXCLUDE`,
  ordered `RULES`, `categorize`, `display_description` (cuts at `LEGAL_REFERENCE`, 160 chars).
- `app/services/address_normalize.py`: `street_key`, `parse_address` -> `ParsedAddress`,
  `number_value`, `find_address_in_text`, `display_from_key` (used by ranking).
- `app/services/address.py`: `REASONS`, `PropertyInfo`, `AddressMatch`, `lookup`, `_candidates`,
  `_property`, `_known_places` (cached set of Boston ZIPs and neighborhoods plus `BOSTON`).
- `app/services/boston.py`: `context_for_address` -> `BuildingContext` of kind `building`,
  `area`, or `none`; `building_history`, `area_context`, `history_for_parcel`, `snapshot_date`,
  `get_boston_db` (FastAPI dependency so tests can swap the DB).
- `scripts/lookup.py`: prints a match from the command line.

### Rental classification (`classify`)
| Land use | Rental when | Reason text |
|---|---|---|
| R2, R3, R4, A, RC | always | multi-family building |
| CM | any CD unit has `OWN_OCC = N` | condo building with X of Y units not owner-occupied |
| R1, CD | `OWN_OCC = N` | not owner-occupied |
| E | never | tax-exempt property (not classified) |
| other | never | not a residential building |

A `CD` row whose building has no `CM` record becomes `CM` if the group has more than one unit.

### Matching order (`lookup`)
1. Parse. No number -> `no_number`. No DB file -> `data_unavailable`.
2. ZIP not in Boston, or (no ZIP and place not a Boston neighborhood or `BOSTON`) -> `outside_boston`.
3. Same `street_key`, number inside `[number_from, number_to]`.
4. None found and street has one word -> `street_key LIKE '<word> %'`, `no_suffix`.
5. Filter by ZIP if given, else by typed neighborhood (if it leaves any rows).
6. No rows -> `not_found`. More than one `(street_key, zip)` -> `ambiguous` with ZIPs.
7. Best row: exact number, then primary, then narrowest range. `match_type` `exact` or `range`.

### Context selection (`context_for_address`)
| Case | Kind | Data |
|---|---|---|
| blank address | `None` | none |
| `data_unavailable`, or no history tables | none | reason |
| matched rental | building | `BuildingHistory` |
| matched non-rental | area | ZIP, else ward, plus city; reason quotes `rental_reason` |
| `outside_boston` | none | reason |
| other unmatched, ZIP typed, ZIP row exists | area | ZIP plus city |
| other unmatched otherwise | none | reason, candidate ZIPs |

## Data Models (`data/boston.sqlite`)
Schema from `sqlite3 data/boston.sqlite ".schema"`; tables are created by `pandas.to_sql`.

- `addresses`: `sam_id`, `building_id`, `is_primary`, `number_text`, `number_from`, `number_to`,
  `street_key`, `zip`, `ward`, `neighborhood`, `parcel_id`, `display_address`, `lat`, `lon`.
  Indexes `idx_addr_street (street_key, zip)`, `idx_addr_parcel (parcel_id)`.
- `properties`: `parcel_id`, `land_use`, `land_use_desc`, `units`, `owner_occupied`, `is_rental`,
  `rental_reason`, `year_built`, `year_remodeled`, `heat_type`. Unique `idx_prop_parcel`.
- `records` (rentals only): `parcel_id`, `date`, `source` (`rentsmart` | `isd_violations`),
  `kind` (`violation` | `complaint`), `category`, `description`, `status` (ISD only).
  Index `idx_records_parcel (parcel_id, date)`.
- `permits` (rentals only): `parcel_id`, `issued_date`, `kind` (`fire_alarm` | `sprinkler` |
  `electrical`), `permit_type`, `status`. Index `idx_permits_parcel (parcel_id, issued_date)`.
- `area_stats` (all buildings): `level` (`zip` | `ward` | `city`), `area_key`,
  `rental_buildings`, `since`, `total`, `violations`, `complaints`, `open_violations`,
  `n_smoke_alarms`, `n_egress`, `n_fire_protection`, `n_heating`, `n_electrical`.
  Unique `idx_area (level, area_key)`.
- `construction` (all buildings, block level): `parcel_id`, `lat`, `lon`, `block_label`, `kind`,
  `work_label`, `issued_month`, `status`. Index `idx_construction_latlon (lat, lon)`. Built by
  `scripts/construction.py` from the permits CSV; never shown for the matched parcel.
- `census_zip` (only when `data/raw/datacommons.json` exists): `zip`, `housing_units`,
  `built_before_1940`, `renter_occupied`, `owner_occupied`, `year`, `fetched`. Unique
  `idx_census_zip (zip)`. Area context only.
- Both tables are specified in `.kiro/specs/nearby-construction-and-census/`.
- `meta`: `key`, `value`. Keys: `snapshot_date`, `addresses`, `properties`, and one per history,
  `construction`, or `census_zip` table.

Notes from the code: `area_stats.total` counts records in the last 12 months, but
`open_violations` counts open records of any date. `open_violations` is stored but not read into
`AreaStats`. `AreaStats.per_100_rentals` divides all-building records by rental buildings.

## Error handling
- Fetch: unknown dataset names exit before any download. HTTP errors other than redirects raise.
  A failed download leaves the old `.csv` in place (only the `.part` file is partial).
- Preprocess: missing `sam.csv` or `assessment.csv` exits with the fetch command. Missing history
  files skip history tables with a printed hint. Bad years and numbers coerce to null. The DB is
  swapped in atomically.
- Runtime: `lookup` never raises for bad input; it returns a reason key from `REASONS`.
  `context_for_address` returns kind `none` when data or history tables are missing.
  `snapshot_date` returns `None` on `sqlite3.Error`. All connections use `mode=ro`.
- `_known_places` and `_snapshot` are `lru_cache`d by path, so a DB rebuilt in place is only seen
  after a restart. The deployed DB is built at image build time, so this is acceptable.

## Privacy considerations
- Rule 1 (whitelists): every raw CSV is read with `usecols` set to a whitelist constant
  (`SAM_COLUMNS`, `ASSESSMENT_COLUMNS` in `preprocess_boston.py`; `RENTSMART_COLUMNS`,
  `VIOLATION_COLUMNS`, `PERMIT_COLUMNS` in `history.py`). None includes the fields listed in the
  steering file. Raw CSVs stay in `data/raw/`, never enter git, the Docker context, or the final
  image.
- Rule 2 (rentals only): `rental_only` filters `records` and `permits` at build time.
  `context_for_address` only calls `building_history` for matched rentals. `history_for_parcel`
  rechecks `is_rental` before reading records, as defense in depth.
- Area fallback: non-rentals and unmatched addresses get ZIP, ward, or city aggregates only. The
  `records` table drops `zip` and `ward` so it can't be used as an area-level per-building index.
- Descriptions: `display_description` removes regulation citations, matching the content rule
  that sources are cited by name only.
- No raw address input is stored by this feature; lookups are in memory.

## Testing strategy
All tests build a small DB from fixture CSVs with the real preprocessing code. The fixture CSVs
include `OWNER`, `MAIL_*`, `owner`, `contact_*`, `applicant`, and `comments` columns with marker
values (`TEST OWNER`, `SECRET`, `TEST APPLICANT`) on purpose. `tests/conftest.py` points the app
at a nonexistent Boston DB by default, so no test reads the real one.

- `tests/fixtures/boston_csv.py`, `tests/fixtures/boston_db.py`: fixture data and builder.
- `tests/test_address.py`: `street_key`, `parse_address`, no-number cases, `classify` table,
  no owner or mail columns or values, building-level addresses, condo roll-up, meta snapshot,
  exact, range, no-suffix, ambiguous and neighborhood resolution, `Mt`/`Mount`, every unmatched
  reason, missing DB.
- `tests/test_boston_history.py`: category tagging and exclusions on real description strings,
  `display_description`, no PII in any table, records rentals-only and rolled up, permit kinds,
  area stats (all buildings, 12-month window), building history, non-rental and unmatched area
  fallback, `none` cases, missing history tables, route-level cards, address found in listing,
  "never says safe".
- `tests/test_town.py`: rental detail shows official history; non-rental detail hides it.
- `tests/test_ranking.py`: non-rental parcel records ignored even if injected; `display_from_key`.
- `tests/test_check_routes.py`: address found in the listing text.
- `tests/test_deploy_files.py`: `build_data.sh` executable, strict mode, `--python`, fetch with
  no dataset names before preprocess.
- `tests/test_pipeline.py`: whitelists disjoint from the steering file's forbidden fields;
  `fetch_boston` unknown-name exit, `_resolve` port stripping, `.part` replace and failure (mocked
  `urllib`, no network); partial fetch leaves `SNAPSHOT_DATE` unchanged, full fetch updates it,
  snapshot uses the oldest dataset; `preprocess_boston.main` missing-file exit, history skip, and
  full build; `scripts/lookup.py` usage, matched, unmatched, ambiguous, and no assessment record.

Run with `.venv/bin/pytest -q`.

## Known gaps
None open. The four earlier gaps are fixed:
1. Snapshot date on partial fetch (Requirement 1.7). `fetch_boston.main` now records per-dataset
   dates in `SNAPSHOT_DATES.json` and writes `SNAPSHOT_DATE` only on a full fetch;
   `snapshot_for` uses the oldest date (`tests/test_pipeline.py`).
2. Whitelist test coverage (Requirements 3.2 to 3.5).
   `tests/test_pipeline.py::test_whitelists_disjoint_from_forbidden_fields` checks each
   whitelist against the forbidden fields, and `test_no_pii_in_any_table` now includes
   `contact_addr2` and `contact_state`.
3. Permits rentals-only (Requirement 7.2). `tests/test_boston_history.py::test_permits_table_rentals_only`
   asserts the non-rental `1500001000` is not in `permits`.
4. Untested entry points. `scripts/fetch_boston.py`, `preprocess_boston.main`, and
   `scripts/lookup.py` are covered in `tests/test_pipeline.py`.
