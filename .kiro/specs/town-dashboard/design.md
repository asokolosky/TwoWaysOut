# Design: Town dashboard and building ranking

## Overview

The dashboard is a server-rendered FastAPI router (`app/routers/town.py`, prefix `/town`) on
Jinja2 templates with HTMX for filters, paging, and status changes. Ranking is computed on each
request by `app/services/ranking.py` from two SQLite files: the app DB (`data/app.sqlite`,
tenant reports, statuses, revoked sessions) and the read-only Boston DB (`data/boston.sqlite`).
Nothing is cached and no scores are stored. Auth is stdlib only (`hmac`, `hashlib`, `secrets`)
in `app/services/town_auth.py`.

## Data flow

1. Request hits `SecurityHeaders` (`app/main.py`), which adds `no-store`, `Pragma: no-cache`,
   and `Referrer-Policy: no-referrer` for `/town` paths.
2. The route calls `_guard`: closed with 503 unless `town_auth.is_configured`, then
   `_session` verifies the cookie and checks `revoked_sessions`.
3. `GET /town`: `_clean_filters` validates ZIP and category, `rank_real_buildings` reads
   `reports WHERE is_simulated = 0` and Boston `records`/`properties`/`addresses`, then
   `get_statuses` joins inspection status for the shown rows. `rank_simulated` reads
   `simulated_reports` separately. An HTMX request with `HX-Target: town-results` gets only
   `partials/town_results.html`.
4. `GET /town/building?key=`: `_find_building` reruns the unfiltered ranking and picks the key,
   `building_reports` loads real reports, `history_for_parcel` loads city history for likely
   rentals only.
5. `POST /town/building/status`: CSRF check, status value check, building lookup, then
   `set_status` upserts `building_status`.
6. `_render` adds `csrf_token` and `signed_in` to every signed-in template.

## Components

| File | Role |
|---|---|
| `app/routers/town.py` | Routes `/town/login` (GET, POST), `/town/logout`, `/town`, `/town/building`, `/town/building/status`, `/town/simulated/{sim_building}`. Login limiter, filter cleaning, CSRF checks, `building_url`. |
| `app/services/ranking.py` | `rank_real_buildings`, `rank_simulated`, `building_reports`, `report_weight`, `decay`, `official_score`. Dataclasses `RankedBuilding`, `SimulatedBuilding`, `BuildingReport`. |
| `app/services/town_auth.py` | `is_configured`, `check_password`, `issue_session`, `session_info`, `csrf_token`, `check_csrf`, `revoke_session`, `is_revoked`. |
| `app/services/building_status.py` | `STATUSES`, `STATUS_LABELS`, `get_statuses`, `get_status`, `set_status`. Never read by ranking. |
| `app/services/rate_limit.py` | `RateLimiter` with HMAC-hashed keys, `allow` and `refund`. |
| `app/services/fire_categories.py` | Boston fire categories used for official hazard labels and the "(any source)" filters. |
| `app/content/report_categories.py` | Tenant categories, severities, and links to fire categories. |
| `app/content/copy.py` | `RANKING_STATEMENT`, exposed as a Jinja global in `app/templating.py`. |
| `app/config.py` | `dashboard_password`, `session_secret`, `app_db_path`, `force_secure_cookies`. |
| `app/db.py` | Schema for `reports`, `simulated_reports`, `building_status`, `revoked_sessions`. |
| `app/main.py` | `SecurityHeaders` middleware. |
| Templates | `town_login.html`, `town_dashboard.html`, `partials/town_results.html`, `town_building.html`, `partials/town_status.html`, `partials/town_status_pill.html`, `partials/town_nav.html`, `town_simulated.html`, `town_not_found.html`, `town_not_configured.html`. |

## Scoring

Constants in `app/services/ranking.py`: `HALF_LIFE_DAYS = 90`, `OFFICIAL_CAP = 10`,
`OPEN_VIOLATION_POINTS = 3`, `RECENT_RECORD_POINTS = 1`, `RECENT_WINDOW_YEARS = 1`,
`TOP_HAZARDS = 3`.

```
decay(age_days)        = 0.5 ** (max(age_days, 0) / 90)
report_weight          = severity(category) x decay(as_of - (observed_date or created_at))
tenant_score           = sum of report_weight over the building's real reports
official_score         = min(10, 3 x open_violations + 1 x recent_records)
total_score            = tenant_score + official_score
```

- Severity: `no_second_exit` 5, `smoke_alarm` 5, `blocked_exit` 4, `electrical_hazard` 4,
  `heating_hazard` 3, `other` 1. Unknown ids fall back to `other`.
- One score per report: `reports.category` holds the most serious selected problem, chosen by
  `order_categories` in `app/services/reports.py` at save time. `extra_categories` adds to hazard
  label weights and the category filter, never to `tenant_score`.
- `open_violations`: records with `kind = 'violation' AND status = 'Open'`, any date.
  `recent_records`: any fire-related record dated within one year before the Boston
  `meta.snapshot_date`. Only parcels joined to `properties.is_rental = 1` are counted.
- Official-only parcels are listed when their official score is above 0.
- Sort: total desc, tenant desc, latest activity desc, display address asc, building key asc
  (`_sort_and_rank`). Simulated sort by tenant score with `sim_building` as the name key.
- No input from `year_built`, ZIP, neighborhood, demographics, `area_stats`, or
  `building_status` enters a score. ZIP and ward are read only for display and the ZIP filter.

## Data models

- `reports` (app DB): `address_input`, `address_key`, `parcel_id`, `ward`, `zip`, `category`,
  `extra_categories`, `description`, `observed_date`, `created_at` (day precision),
  `is_simulated` (0 or 1), `status`.
- `simulated_reports`: `sim_building`, `ward`, `rental_type`, `category`, `description`,
  `observed_date`, `created_at`. No address, parcel, SAM ID, or ZIP columns.
- `building_status`: `building_key` (PK), `status` (CHECK open/scheduled/inspected),
  `updated_on`.
- `revoked_sessions`: `nonce` (PK), `expires_at` (Unix seconds).
- Building key (`building_key_for`): `address_key` if set (`PARCEL <id>` for matched Boston
  addresses, else normalized `NUMBER STREET ZIP`), then `PARCEL <parcel_id>`, then `text_key` of
  the typed address, then opaque `UNKEYED <id>`.
- `RankedBuilding` returns tenant, official, and total scores plus `open_violations` and
  `recent_official_records`, so templates can show each part.
- `SimulatedBuilding` has no address, parcel, or ZIP fields and `is_simulated = True`.

## Auth and session design

- Configured only when `DASHBOARD_PASSWORD` is set and `SESSION_SECRET` has at least 32
  characters (`MIN_SECRET_CHARS`). Otherwise every town route returns 503.
- Password check: `hmac.compare_digest` on SHA-256 digests, so timing doesn't leak length. The
  password is never stored, logged, or put in a token.
- Token: `<issued_at>.<nonce>.<hex HMAC-SHA256("session|issued_at|nonce")>`. Max age 8 hours,
  60-second clock skew allowance, 256-character and ASCII limits checked before parsing.
- Cookie `tw_town_session`: `Path=/town`, `HttpOnly`, `SameSite=Lax`, `Secure` when the scheme
  is `https` or `force_secure_cookies` is true.
- Sign-out writes the nonce to `revoked_sessions` until natural expiry and prunes expired rows,
  so a copied cookie stops working. Other sessions are untouched. Rotating `SESSION_SECRET`
  ends all sessions.
- CSRF: HMAC-SHA256 over `csrf|<nonce>`, in a hidden `csrf_token` field or `X-CSRF-Token`
  header, required on logout and status POSTs.
- Login limiter: 5 failed attempts per hashed client IP per 15 minutes, in memory. An attempt
  is reserved before the check and refunded on success.

## Error handling

| Case | Response |
|---|---|
| Not configured | 503, `town_not_configured.html` |
| Signed out | 303 to `/town/login`, or 200 with `HX-Redirect` for HTMX |
| Wrong password | 401, "That password isn't right." |
| Too many attempts | 429, "Too many sign-in attempts. Please wait 15 minutes and try again." |
| Bad or missing CSRF | 403, "This form expired. Reload the page and try again." |
| Bad status value | 422, "Choose open, scheduled, or inspected." |
| Over-length form field | 422 friendly page from the app's `RequestValidationError` handler |
| Unknown building or simulated ID | 404, `town_not_found.html` |
| Bad ZIP filter | Ignored, alert "Enter a 5-digit ZIP code." |
| Missing DB, table, or snapshot | Empty or tenant-only ranking, no error |

## Privacy and security considerations

- Real ranking and detail read only `reports WHERE is_simulated = 0`; `simulated_reports` is
  read only by `rank_simulated` and `_simulated_reports`. Ranking and simulated reads open
  databases with `mode=ro`.
- City address, parcel ID, and official history are used only for likely rentals.
- `address_input` is never displayed. Tenant dates are shown by month. Descriptions are already
  scrubbed of emails and phone numbers at save time and are HTML-escaped by Jinja.
- Building keys appear in URLs, so town pages send `Referrer-Policy: no-referrer`.
- Signed-in pages send `Cache-Control: no-store` and `Pragma: no-cache`. Every town template sets
  `hx-history="false"` on `<body>` (through the `body_attrs` block in `base.html`), so htmx
  doesn't write town page snapshots to `localStorage` on `hx-push-url` navigations. Logout also
  sends `Clear-Site-Data: "cache", "storage"` as a second layer.
- The login limiter's client IP depends on uvicorn's forwarded-header trust. The entrypoint
  trusts only `FORWARDED_ALLOW_IPS` (default `127.0.0.1`); setting Render's range is a deploy
  step tracked in `.kiro/specs/platform-and-deploy/`.
- The dashboard is behind a single shared password, with no per-user accounts or audit log.

## Known gaps

The three earlier gaps are fixed in code and tests:

1. HTMX history cache. htmx 2.x saves a page snapshot to `localStorage` before each
   `hx-push-url` navigation by default. Town templates now set `hx-history="false"`, and logout
   sends `Clear-Site-Data: "cache", "storage"` (`tests/test_town_history.py`). Still open: this
   is based on htmx's documented behavior and hasn't been confirmed in a browser's storage panel.
2. Ranking inputs. `tests/test_town_history.py::test_ranking_never_reads_area_or_outreach_data`
   checks that `ranking.py` never mentions `area_stats`, `census_zip`, census, construction, or
   Data Commons and doesn't import the census or construction services.
3. Text style. `tests/test_final_checks.py::test_visible_text_has_no_em_dash_or_exclamation` now
   renders the signed-in building detail and simulated detail pages too.

## Testing strategy

All tests use `tests/conftest.py` overrides: settings with `_env_file=None`, a temp app DB, a
fixture Boston DB, and no AI client. They never read `.env` or the real databases.

| Test file | Covers |
|---|---|
| `tests/test_ranking.py` | Severity table, exact decay, observed vs created date, sums, `is_simulated = 1` rows ignored, official formula and cap, total, non-rental handling, missing Boston DB, year built and ZIP not changing scores, snapshot window, simulated isolation and masking, tie-breaking, filters, limit, address display, day precision, read-only access |
| `tests/test_report_multiselect.py` | One score per report at its most serious problem, extra problems feed hazards and filters, old DB without `extra_categories`, simulated untouched |
| `tests/test_town.py` | 503 when unconfigured, redirects, HX-Redirect, login a11y, 401, rate limit, cookie flags, tampered and expired cookies, logout CSRF, ranking statement and order, score parts, simulated badges and masking, filters, paging, detail dates, official history rules, 404, status updates and rejections, password never in responses |
| `tests/test_town_hardening.py` | Clear-Site-Data, header policy, revocation and pruning, other sessions survive, `force_secure_cookies`, non-ASCII cookies and tokens, digest compare, limiter refund and reservation |
| `tests/test_town_security.py` | Revoked cookie, cookie path, secret rotation, GET doesn't change status, CSRF exact match and cross-session, overlong key, simulated ID not a real building, status value strictness, password edge cases, every route signed-out, HTML escaping, no full dates, simulated never in real results, no-store and no-referrer, dashboard and detail accessibility |
| `tests/test_final_checks.py` | Town security headers, ranking statement on dashboard and detail, no em dashes or exclamation points on login, dashboard, building detail, and simulated detail |
| `tests/test_town_history.py` | `hx-history="false"` on signed-in, signed-out, and every town template; public pages keep history; logout clears cache and storage; ranking never reads area or outreach data |
| `tests/test_pages.py` | Exact `RANKING_STATEMENT` value |
| `tests/test_e2e.py` | Student report through to the dashboard, accessibility on town pages |

Run with `.venv/bin/pytest -q`.
