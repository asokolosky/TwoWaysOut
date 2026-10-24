# Design: Anonymous tenant hazard reports

## Overview

A tenant fills in `/report`, the router checks the honeypot and the rate limit, and
`save_report` validates, redacts, matches the address against Boston data, and inserts one row
into `reports` with `is_simulated = 0`. The confirmation page shows what was saved and where to
file an official request. The ranking service reads those rows for the town dashboard.
Simulated demo reports are written by a separate script into their own table and are ranked on
their own.

## Data flow

```
GET /report[?address=...]          -> report_form()   -> report_form.html
POST /report (form fields)         -> report_submit()
  1. too many category values      -> replaced with an invalid marker (fails in step 4)
  2. website (honeypot) filled     -> report_thanks.html, saved=None, nothing stored
  3. limiter.allow(client IP)      -> False: 429 + form
  4. save_report() in threadpool   -> ReportError: 422 + form
       normalize + validate address, order_categories(), redact_contact_info(),
       parse_observed(), lookup() against boston.sqlite, INSERT INTO reports (..., 0)
  5. report_thanks.html with SavedReport
RequestValidationError on /report  -> app/main.py validation_error() -> form, 422, generic message

scripts/seed_reports.py            -> load_combos(boston.sqlite aggregates) -> build_rows()
                                   -> DELETE + INSERT simulated_reports
app/services/ranking.py            -> rank_real_buildings(): reports WHERE is_simulated = 0
                                   -> rank_simulated(): simulated_reports only
```

## Components

- `app/routers/report.py`: `GET /report` and `POST /report`. `get_report_limiter` is a FastAPI
  dependency holding one module-level `RateLimiter(settings.reports_per_hour, 3600)`, rebuilt if
  the setting changes. Form fields have hard caps (`address` 2,000, `description` 10,000,
  `observed_date` 200, `website` 200). `checked` holds only known category IDs for re-rendering.
  `save_report` runs in a threadpool because it does blocking SQLite work.
- `app/services/reports.py`: `save_report`, `order_categories`, `split_categories`,
  `redact_contact_info`, `has_contact_info`, `address_key`, `text_key`, `parse_observed`,
  `count_reports`, `ReportError`, and the `SavedReport` dataclass. Limits: `MAX_ADDRESS_CHARS =
  200`, `MAX_DESCRIPTION_CHARS = 1000`, `EARLIEST_OBSERVED = 2000-01-01`.
- `app/services/rate_limit.py`: `RateLimiter`, a sliding-window limiter keyed by
  HMAC-SHA256(per-process random salt, IP). Thread-safe with a lock. Sweeps stale keys every
  `SWEEP_EVERY_CALLS = 500` calls or at `SWEEP_AT_SIZE = 10_000` keys. `refund` and `is_limited`
  are used by the town login, not by reports.
- `app/content/report_categories.py`: `REPORT_CATEGORIES` (id, label, hint, severity,
  fire_category, department) and the Boston 311 and Inspectional Services URLs.
- `app/db.py`: `SCHEMA`, `init_db` (schema plus the `extra_categories` migration), `connect`,
  `db_path`, and the `get_app_db` dependency, which applies the schema once per process path or
  again if the file was deleted.
- `app/services/address.py` (`lookup`, `AddressMatch`) and `app/services/address_normalize.py`
  (`parse_address`): used to match and normalize addresses. Not changed by this feature.
- `app/main.py`: disables the `uvicorn.access` logger at import, caps request bodies with
  `LimitRequestSize`, and maps `RequestValidationError` on `/report` to the form with
  `TOO_LONG_MESSAGE`, without echoing values.
- `app/templates/report_form.html`: the form, error alert, 911 notice, honeypot, and
  anonymity statement.
- `app/templates/report_thanks.html`: the confirmation page, the redaction note, Boston or
  non-Boston next steps, and `partials/disclaimer.html`.
- `scripts/seed_reports.py`: `load_combos`, `build_rows`, `seed`, `main`. Constants: `SEED =
  20261024`, `NUM_BUILDINGS = 14`, `REPORTS_PER_BUILDING` (sums to 40), `DAYS_BACK = 180`,
  `MAX_CREATED_LAG_DAYS = 5`, `MIN_GROUP_SIZE = 20`, `STUDENT_WARD_BOOST = 25`.
- `docker/entrypoint.sh`: seeds when `SEED_SIMULATED=1` and the simulated table is empty or
  missing; runs uvicorn with `--no-access-log --proxy-headers`.
- `app/services/ranking.py`: consumer of `reports` and `simulated_reports` (see Requirement 12).

## Data models

`reports` (`app/db.py`):

| Column | Type | Notes |
| --- | --- | --- |
| id | INTEGER PK AUTOINCREMENT | |
| address_input | TEXT NOT NULL | as typed, whitespace collapsed; never displayed by ranking |
| address_key | TEXT | `PARCEL <id>` or "NUMBER STREET ZIP/place" |
| display_address | TEXT | Boston official address when matched |
| parcel_id, sam_id | TEXT | when matched |
| ward | INTEGER | when matched |
| zip | TEXT | matched ZIP, else parsed from the typed address |
| category | TEXT NOT NULL | most serious selected problem, used for scoring |
| extra_categories | TEXT | other selected IDs, comma-separated, or NULL |
| description | TEXT | contact info removed, or NULL |
| observed_date | TEXT | YYYY-MM-DD or NULL |
| created_at | TEXT NOT NULL | YYYY-MM-DD, set explicitly by `save_report` |
| is_simulated | INTEGER NOT NULL DEFAULT 0 | CHECK 0 or 1; always 0 from `save_report` |
| status | TEXT NOT NULL DEFAULT 'open' | CHECK open, scheduled, inspected |

Indexes: `idx_reports_parcel (is_simulated, parcel_id)`, `idx_reports_key (is_simulated,
address_key)`.

`simulated_reports` (`app/db.py`): `id`, `sim_building` (e.g. `SIM-07`), `ward`, `rental_type`,
`category`, `description` (fictional), `observed_date`, `created_at`. No address, parcel, SAM
ID, or ZIP columns. Index `idx_sim_building`.

`SavedReport` (`app/services/reports.py`): `id`, `category_labels` (most serious first),
`department`, `match`, `in_boston`, `redacted`.

Migration: `init_db` reads `PRAGMA table_info(reports)` and adds `extra_categories` if missing.
`ranking._report_columns` reads `NULL AS extra_categories` for unmigrated databases.

## Error handling

- `ReportError` messages from `save_report` are shown as-is with status 422 and the typed values.
- Rate limit: status 429 with the form and typed values.
- Over-cap fields: FastAPI raises `RequestValidationError`; `app/main.py` returns the form with
  status 422 and a generic message, never the submitted values. HTMX requests get the
  `partials/check_error.html` partial with status 200.
- Oversized bodies: `LimitRequestSize` returns 413.
- Honeypot hits get the normal confirmation with `saved=None`, so the page shows only the generic
  next steps.

## Privacy considerations

- No identity fields in the form or schema (`tests/test_reports.py::test_ip_not_stored`,
  `test_form_renders_with_categories_and_911`).
- Contact info: descriptions are redacted before the INSERT; addresses with contact info are
  rejected rather than edited.
- Client IPs: read from `request.client.host`, hashed with a per-process salt inside
  `RateLimiter`, held only in memory, and lost on restart. No IP column, no logging calls, and
  the uvicorn access log is off in both `app/main.py` and `docker/entrypoint.sh`.
- `created_at` and `observed_date` are day precision so a report can't be lined up with a
  timestamped log.
- `is_simulated = 0` is a literal in the INSERT, so a form field can't change it.
- Simulated data is masked: synthetic IDs, ward and rental type only, labels drawn from groups of
  at least 20 likely rentals, fictional text. The seed never touches `reports`.
- Real ranking filters `is_simulated = 0` in SQL and never reads `simulated_reports`.

## Testing strategy

Run `.venv/bin/pytest -q`. `tests/conftest.py` overrides settings (no `.env`), the AI client, the
Boston DB, the app DB (a temp file), the report limiter, and the check limiter.

- `tests/test_reports.py`: form contents, prefill escaping and cap, saving and matching, unit
  grouping, outside-Boston saving, `is_simulated` always 0, every validation message, keeping
  typed values, escaping, redaction (end to end and unit variants, including text that must not
  change), honeypot, rate limit and limiter internals (window, sweeps, no raw IPs, per-instance
  salt), day-precision `created_at`, address contact rejection, no IP or identity columns.
- `tests/test_report_multiselect.py`: checkboxes, most-serious-first storage, single selection,
  invalid and missing selections, re-checked boxes after errors, duplicates, no score inflation,
  extra categories in hazards and filters, migration of an old database, too many values,
  crafted values not echoed, simulated table untouched.
- `tests/test_seed_reports.py`: row and building counts, fallback source, Boston aggregates,
  `MIN_GROUP_SIZE` threshold, determinism and idempotence, categories and dates, `reports`
  untouched, generic descriptions, no location columns, CLI output.
- `tests/test_ranking.py`: `test_simulated_flag_rows_in_reports_ignored`,
  `test_real_ranking_identical_with_simulated_rows`, `test_rank_simulated_is_masked`.
- `tests/test_privacy_hardening.py`: access log disabled, request size limits, friendly page for
  over-cap report fields.
- `tests/test_town_security.py::test_simulated_never_in_real_results_under_any_filter` and
  `tests/test_e2e.py` cover the dashboard side and confirmation page accessibility.

- `tests/test_report_limits.py`: rejected submissions don't use up the limit, the 429 still
  applies once the limit is reached, `save_report` and `count_reports` close their connections,
  and a saved report is committed.

## Known gaps

The three earlier gaps are fixed:

1. Spoofable client IP. The entrypoint now uses
   `--forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}"` instead of `"*"` (criterion 7.8;
   see `.kiro/specs/task-10-finish/` Requirement 1). On Render, the owner still has to confirm the
   proxy range and set the value; until then all visitors share one limit. That deploy step is
   tracked in `.kiro/specs/platform-and-deploy/tasks.md`.
2. Failed submissions used up the limit. `report_submit` still reserves a hit with
   `limiter.allow` before `save_report` (so concurrent requests can't exceed the limit), and now
   calls `limiter.refund(client_ip)` on `ReportError` (criterion 7.7).
3. Connections weren't closed. `save_report` uses `with closing(connect(app_db)) as con, con:`
   (commit, then close) and `count_reports` uses `with closing(sqlite3.connect(...))`
   (criterion 6.6).
