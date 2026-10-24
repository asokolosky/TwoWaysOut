# Implementation Plan

- [x] 1. Report categories and severities
  - [x] 1.1 Define `REPORT_CATEGORIES` with label, hint, severity, fire category, and department in `app/content/report_categories.py`
    - _Requirements: 3.7_

- [x] 2. Database schema and migration
  - [x] 2.1 Create `reports` with no identity or IP columns, `is_simulated` and `status` CHECK constraints, and indexes in `app/db.py`
    - _Requirements: 1.2, 6.4_
  - [x] 2.2 Create `simulated_reports` with only `sim_building`, ward, rental type, category, description, and dates
    - _Requirements: 11.1_
  - [x] 2.3 Apply the schema in `get_app_db` once per process or after the file is deleted
    - _Requirements: 6.1_
  - [x] 2.4 Add `extra_categories` to older databases in `init_db`, tolerating a concurrent add
    - _Requirements: 6.2_
  - [x] 2.5 Read `NULL AS extra_categories` in ranking for unmigrated databases
    - _Requirements: 6.5_

- [x] 3. Report form
  - [x] 3.1 Build `report_form.html` with address, category checkboxes, details, date, honeypot, 911 notice, and anonymity statement
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 8.2_
  - [x] 3.2 Prefill the address from the query string, capped at 200 characters
    - _Requirements: 1.3_

- [x] 4. Validation and saving in `app/services/reports.py`
  - [x] 4.1 Normalize and validate the address, rejecting contact info and missing street numbers
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  - [x] 4.2 Match against Boston data and build `address_key` (parcel or text key)
    - _Requirements: 2.6, 2.7_
  - [x] 4.3 Validate, dedupe, and order categories with `order_categories`
    - _Requirements: 3.1, 3.2, 3.4_
  - [x] 4.4 Store the most serious category in `category` and the rest in `extra_categories`
    - _Requirements: 3.5_
  - [x] 4.5 Validate observed dates and set `created_at` to today's date explicitly
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_
  - [x] 4.6 Insert with a literal `is_simulated = 0`
    - _Requirements: 6.3_

- [x] 5. Contact information redaction
  - [x] 5.1 Redact plain, spaced, and spelled-out emails before saving
    - _Requirements: 4.1_
  - [x] 5.2 Redact North American, local, and international phone numbers before saving
    - _Requirements: 4.2_
  - [x] 5.3 Redact social handles
    - _Requirements: 4.3_
  - [x] 5.4 Leave ordinary numbers and text unchanged
    - _Requirements: 4.4_
  - [x] 5.5 Enforce the 1,000-character description limit and store NULL for empty descriptions
    - _Requirements: 4.6, 4.7_

- [x] 6. Router, rate limiting, and honeypot in `app/routers/report.py`
  - [x] 6.1 Return the confirmation without saving when the honeypot is filled
    - _Requirements: 8.1_
  - [x] 6.2 Limit submissions per client IP with `RateLimiter` and return 429 at the limit
    - _Requirements: 7.1, 7.2, 7.6_
  - [x] 6.3 Hash IPs with a per-process salt, keep them in memory only, and sweep stale keys
    - _Requirements: 7.3, 7.5_
  - [x] 6.4 Disable the uvicorn access log in `app/main.py` and `docker/entrypoint.sh`
    - _Requirements: 7.4_
  - [x] 6.5 Reject more category values than categories
    - _Requirements: 3.3_

- [x] 7. Errors and confirmation page
  - [x] 7.1 Return 422 with the form, a `role="alert"` error, and typed values on `ReportError`
    - _Requirements: 10.1, 10.4_
  - [x] 7.2 Re-check only known category IDs after an error
    - _Requirements: 10.2_
  - [x] 7.3 Return a generic message for over-cap fields without echoing values (`app/main.py`)
    - _Requirements: 10.3_
  - [x] 7.4 Build `report_thanks.html` with labels, building, department, redaction note, Boston or local next steps, 911, and disclaimer
    - _Requirements: 4.5, 9.1, 9.2, 9.3, 9.4_

- [x] 8. Ranking reads
  - [x] 8.1 Score each real report once at `category` severity; use `extra_categories` for hazards and filters
    - _Requirements: 3.6_
  - [x] 8.2 Read only `reports WHERE is_simulated = 0` for real rankings and only `simulated_reports` for simulated rankings
    - _Requirements: 12.1, 12.2, 12.3_

- [x] 9. Simulated reports seed (`scripts/seed_reports.py`)
  - [x] 9.1 Replace all simulated rows with 40 deterministic rows across `SIM-01` to `SIM-14`
    - _Requirements: 11.2, 11.3_
  - [x] 9.2 Draw labels from Boston aggregates with the `MIN_GROUP_SIZE` threshold, with fallback and top-up
    - _Requirements: 11.4, 11.5, 11.6_
  - [x] 9.3 Use fictional "Simulated report:" descriptions checked against redaction
    - _Requirements: 11.7_
  - [x] 9.4 Seed on container start when `SEED_SIMULATED=1` and the table is empty
    - _Requirements: 11.8_

- [x] 10. Tests
  - [x] 10.1 `tests/test_reports.py`, `tests/test_report_multiselect.py`, `tests/test_seed_reports.py`
    - _Requirements: 1.1, 1.2, 1.3, 2.4, 3.2, 3.5, 3.6, 4.1, 4.2, 4.4, 5.5, 6.2, 6.3, 7.2, 7.3, 8.1, 11.1, 11.2, 11.4_
  - [x] 10.2 Simulated isolation in `tests/test_ranking.py`, `tests/test_town_security.py`; logging in `tests/test_privacy_hardening.py`
    - _Requirements: 7.4, 10.3, 12.1, 12.2_

- [x] 11. Close known gaps
  - [x] 11.1 Stop trusting `X-Forwarded-For` from every peer: `docker/entrypoint.sh` uses `${FORWARDED_ALLOW_IPS:-127.0.0.1}` (`tests/test_deploy_files.py::test_forwarded_ips_never_trust_every_peer`). Setting the Render range after deploy is tracked in `.kiro/specs/platform-and-deploy/tasks.md` task 12.2.
    - _Requirements: 7.1, 7.3, 7.8_
  - [x] 11.2 Rejected submissions don't count: `limiter.refund(client_ip)` on `ReportError` in `app/routers/report.py` (`tests/test_report_limits.py`)
    - _Requirements: 7.1, 7.2, 7.7_
  - [x] 11.3 `save_report` and `count_reports` close their connections with `contextlib.closing` (`tests/test_report_limits.py::test_save_and_count_close_their_connections`)
    - _Requirements: 6.1, 6.6_
