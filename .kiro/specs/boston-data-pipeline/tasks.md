# Implementation Plan

- [x] 1. Download raw datasets
  - [x] 1.1 `DATASETS` map and name filtering with unknown-name exit in `scripts/fetch_boston.py`
    - _Requirements: 1.1, 1.2, 1.3_
  - [x] 1.2 `_resolve` S3 redirect handling and `.csv.part` streaming download
    - _Requirements: 1.4, 1.5_
  - [x] 1.3 Write `data/raw/SNAPSHOT_DATES.json` after a run and `data/raw/SNAPSHOT_DATE` after a full fetch (task 15); keep `data/raw/` in `.gitignore` and `.dockerignore`
    - _Requirements: 1.6, 1.8_

- [x] 2. One-step build
  - [x] 2.1 `scripts/build_data.sh` with `--python`, strict mode, fetch then preprocess from the project root
    - _Requirements: 2.1, 2.2, 2.3_
  - [x] 2.2 Docker builder runs the script, deletes `data/raw`, copies only `boston.sqlite` (0444)
    - _Requirements: 2.4, 1.8_
  - [x] 2.3 `tests/test_deploy_files.py` checks executable bit, strict mode, `--python`, and order
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 3. Owner and contact field whitelists
  - [x] 3.1 `SAM_COLUMNS` and `ASSESSMENT_COLUMNS` in `scripts/preprocess_boston.py`, read with `usecols`
    - _Requirements: 3.1, 3.2, 3.6_
  - [x] 3.2 `RENTSMART_COLUMNS`, `VIOLATION_COLUMNS`, `PERMIT_COLUMNS` in `scripts/history.py`, read with `usecols`
    - _Requirements: 3.3, 3.4, 3.5, 3.6_
  - [x] 3.3 Fixture CSVs include forbidden columns with marker values; tests check no owner, mail, applicant, or marker values in the DB
    - _Requirements: 3.7_

- [x] 4. Building-level address table
  - [x] 4.1 `build_addresses`: unit rows dropped, ranges, swap, number parsing, parcel and ZIP padding
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.6_
  - [x] 4.2 Shared `street_key` used by preprocessing and lookup
    - _Requirements: 4.5_

- [x] 5. Properties and rental detection
  - [x] 5.1 `classify` rules and reasons
    - _Requirements: 5.2, 5.3, 5.4, 5.5, 5.6_
  - [x] 5.2 `build_properties`: condo roll-up, unit counts, year cleanup, condo fallbacks
    - _Requirements: 5.1, 5.7, 5.8_
  - [x] 5.3 Tests: `test_rental_rule`, `test_condo_units_roll_up`, owner-occupied single family
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 6. Fire-related records and permits
  - [x] 6.1 `categorize` with ordered `RULES` and `EXCLUDE` in `app/services/fire_categories.py`
    - _Requirements: 6.1, 6.2_
  - [x] 6.2 `build_records`: RentSmart kinds, ISD SAM-to-parcel join, building roll-up
    - _Requirements: 6.3, 6.4, 6.5_
  - [x] 6.3 `display_description` cuts legal references and limits length
    - _Requirements: 6.6_
  - [x] 6.4 `build_permits`: fire alarm, sprinkler, electrical by work type or permit type
    - _Requirements: 6.5, 6.7_
  - [x] 6.5 Tests in `tests/test_boston_history.py` on real description strings and permit kinds
    - _Requirements: 6.1, 6.2, 6.4, 6.5, 6.6, 6.7_

- [x] 7. Rentals-only building history
  - [x] 7.1 `rental_only` applied to `records` and `permits`; `zip` and `ward` dropped from `records`
    - _Requirements: 7.1, 7.2, 7.5_
  - [x] 7.2 `context_for_address` returns building history only for rentals
    - _Requirements: 7.3_
  - [x] 7.3 `history_for_parcel` rechecks `is_rental`
    - _Requirements: 7.4_
  - [x] 7.4 Tests: records rentals-only, non-rental area fallback, town non-rental detail, injected non-rental records ignored in ranking
    - _Requirements: 7.1, 7.3, 7.4_

- [x] 8. Area statistics
  - [x] 8.1 `build_area_stats`: ZIP, ward, city rows from all buildings, 12-month window, category counts, rental building counts
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
  - [x] 8.2 `test_area_stats_cover_all_buildings`
    - _Requirements: 8.1, 8.3_

- [x] 9. Database output
  - [x] 9.1 `write_db`: temp file swap, tables, indexes, `meta`
    - _Requirements: 9.1, 9.2, 9.3_
  - [x] 9.2 `main`: required file check, optional history files
    - _Requirements: 9.4, 9.5_

- [x] 10. Address parsing and normalization
  - [x] 10.1 `street_key` and `parse_address` in `app/services/address_normalize.py`
    - _Requirements: 10.1, 10.2, 10.3, 10.4_
  - [x] 10.2 `find_address_in_text`, used by `app/routers/check.py` when the address field is blank
    - _Requirements: 10.5_
  - [x] 10.3 Tests: `test_street_key`, `test_parse_address`, `test_parse_address_without_number`, address found in listing
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

- [x] 11. Address matching
  - [x] 11.1 `lookup` with range match, ordering, no-suffix retry, ZIP and neighborhood filters, ambiguity
    - _Requirements: 11.1, 11.2, 11.3_
  - [x] 11.2 Reason keys and texts in `REASONS`; read-only parameterized queries
    - _Requirements: 11.4, 11.5, 11.6, 11.7_
  - [x] 11.3 Tests in `tests/test_address.py` for each match type and reason
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

- [x] 12. Building or area context
  - [x] 12.1 `context_for_address`, `building_history`, `area_context` in `app/services/boston.py`
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_
  - [x] 12.2 Area card labeled as area, not building (`test_report_shows_area_card`)
    - _Requirements: 12.7_
  - [x] 12.3 Tests for building, area, none, blank, and no-history cases
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

- [x] 13. Town dashboard support
  - [x] 13.1 `history_for_parcel` with primary address and guards; `snapshot_date`
    - _Requirements: 13.1, 13.2, 13.3_
  - [x] 13.2 `tests/test_town.py` rental and non-rental detail pages
    - _Requirements: 13.1_

- [x] 14. Command-line lookup
  - [x] 14.1 `scripts/lookup.py` prints match, building, and reasons
    - _Requirements: 14.1, 14.2, 14.3_

- [x] 15. Fix snapshot date on partial fetch
  - [x] 15.1 `scripts/fetch_boston.py` records per-dataset dates in `SNAPSHOT_DATES.json` and writes `SNAPSHOT_DATE` only on a full fetch; `preprocess_boston.snapshot_for` uses the oldest date
    - _Requirements: 1.6, 1.7_
  - [x] 15.2 `tests/test_pipeline.py`: partial fetch leaves `SNAPSHOT_DATE` unchanged, full fetch updates it, snapshot uses the oldest dataset
    - _Requirements: 1.6, 1.7_

- [x] 16. Close privacy test gaps
  - [x] 16.1 `tests/test_pipeline.py::test_whitelists_disjoint_from_forbidden_fields` checks each whitelist against the steering file's forbidden fields
    - _Requirements: 3.2, 3.3, 3.4, 3.5_
  - [x] 16.2 `contact_addr2` and `contact_state` added to the column check in `test_no_pii_in_any_table`
    - _Requirements: 3.4, 3.7_
  - [x] 16.3 `tests/test_boston_history.py::test_permits_table_rentals_only` asserts `permits` excludes the non-rental parcel `1500001000`
    - _Requirements: 7.2_

- [x] 17. Test untested pipeline entry points (`tests/test_pipeline.py`)
  - [x] 17.1 `fetch_boston`: unknown-name exit, `_resolve` port stripping, `.part` replace and failure (mocked `urllib`, no network)
    - _Requirements: 1.3, 1.4, 1.5_
  - [x] 17.2 `preprocess_boston.main`: missing required file exit, history-skip branch, and full build, using a temp `RAW_DIR` and `DB_PATH`
    - _Requirements: 9.4, 9.5_
  - [x] 17.3 `scripts/lookup.py`: usage, matched, unmatched and ambiguous, and no assessment record
    - _Requirements: 14.1, 14.2, 14.3_

- [x] 18. Nearby construction and area housing data (details in `.kiro/specs/nearby-construction-and-census/`)
  - [x] 18.1 `construction` table from the permits CSV and `census_zip` table from `data/raw/datacommons.json` in `scripts/preprocess_boston.py`
    - _Requirements: 9.2, 9.3_
  - [x] 18.2 Optional `scripts.fetch_datacommons` step in `scripts/build_data.sh`, skipped without a key and non-fatal on failure
    - _Requirements: 2.5_
