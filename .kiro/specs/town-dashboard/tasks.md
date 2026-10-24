# Implementation Plan

- [x] 1. Close the dashboard unless configured, and add password sign-in
  - [x] 1.1 `town_auth.is_configured` and the 503 `town_not_configured.html` page on every town route
    - _Requirements: 1.1_
  - [x] 1.2 `_guard` and `_to_login` with 303 redirect, HX-Redirect for HTMX, and signed-in redirect from `/town/login`
    - _Requirements: 1.2, 1.3, 1.4_
  - [x] 1.3 `check_password` with SHA-256 digests and `hmac.compare_digest`, 401 message, no echo
    - _Requirements: 1.5, 1.6, 1.11_
  - [x] 1.4 Login limiter: 5 failures per hashed IP per 15 minutes, reserve before check, refund on success
    - _Requirements: 1.7, 1.8, 1.9, 1.10_

- [x] 2. Signed sessions and server-side sign-out
  - [x] 2.1 `issue_session` and `session_info` with HMAC-SHA256, 8-hour expiry, skew, length and ASCII checks
    - _Requirements: 2.1, 2.4, 2.5_
  - [x] 2.2 Cookie flags: `Path=/town`, `HttpOnly`, `SameSite=Lax`, `Secure` on https or `force_secure_cookies`
    - _Requirements: 2.2, 2.3_
  - [x] 2.3 `revoked_sessions` table, `revoke_session` with pruning, `is_revoked` check in `_session`
    - _Requirements: 2.6, 2.7, 2.8_
  - [x] 2.4 Logout deletes the cookie and sends `Clear-Site-Data: "cache", "storage"` only on success
    - _Requirements: 2.6, 2.9_

- [x] 3. CSRF tokens on state-changing POSTs
  - [x] 3.1 `csrf_token` and `check_csrf`, rendered by `_render`, accepted from form field or `X-CSRF-Token`
    - _Requirements: 3.1, 3.2, 3.3_

- [x] 4. Town response headers in `SecurityHeaders` (`app/main.py`)
  - [x] 4.1 `no-store`, `Pragma: no-cache`, `Referrer-Policy: no-referrer` for `/town` paths
    - _Requirements: 4.1, 4.2_

- [x] 5. Ranking statement
  - [x] 5.1 `RANKING_STATEMENT` in `app/content/copy.py`, shown on the dashboard and building detail
    - _Requirements: 5.1, 5.2, 5.3_

- [x] 6. Tenant score
  - [x] 6.1 `decay` and `report_weight` with a 90-day half-life and the severity table
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.8_
  - [x] 6.2 Score each report once at `reports.category`; `extra_categories` only for hazards and filters
    - _Requirements: 6.5, 6.6, 6.7_

- [x] 7. Official score
  - [x] 7.1 `official_score` with 3 x open violations + 1 x records in 12 months, capped at 10
    - _Requirements: 7.1, 7.3_
  - [x] 7.2 `_snapshot_window` from the Boston snapshot date, with the February 29 case
    - _Requirements: 7.2_
  - [x] 7.3 Rental-only join, non-rental handling, official-only buildings, missing data fallbacks
    - _Requirements: 7.4, 7.5, 7.6, 7.7_

- [x] 8. Total, separate score parts, and order
  - [x] 8.1 `RankedBuilding` returns tenant, official, and total; templates show each part and the counts behind official
    - _Requirements: 8.1, 8.2, 8.3_
  - [x] 8.2 `_sort_and_rank` tie-breaking and top 3 hazard labels
    - _Requirements: 8.4, 8.5_
  - [x] 8.3 "How scores work" section on the dashboard
    - _Requirements: 8.6_

- [x] 9. Keep excluded inputs out of ranking
  - [x] 9.1 No building age, ZIP, neighborhood, demographics, or status in scoring; ZIP and ward for display and filter only
    - _Requirements: 9.1, 9.2, 9.3_
  - [x] 9.2 `tests/test_town_history.py::test_ranking_never_reads_area_or_outreach_data` asserts `ranking.py` never reads `area_stats`, `census_zip`, census, construction, or Data Commons data and doesn't import those services
    - _Requirements: 9.1_

- [x] 10. Real ranking reads only real reports
  - [x] 10.1 `_real_reports` and `building_reports` filter `is_simulated = 0` in SQL and open DBs read-only
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

- [x] 11. Separate, masked SIMULATED section
  - [x] 11.1 `rank_simulated` from `simulated_reports` only, same formula, masked `SimulatedBuilding`
    - _Requirements: 11.1, 11.3_
  - [x] 11.2 Dashboard section, badges, and banner in `town_dashboard.html` and `town_simulated.html`
    - _Requirements: 11.2, 11.5_
  - [x] 11.3 `/town/simulated/{id}` with `SIM_RE` validation and 404
    - _Requirements: 11.4, 11.6_

- [x] 12. Filters and paging
  - [x] 12.1 `_clean_filters` for ZIP and category, `CATEGORY_OPTIONS`, `_matches_category`
    - _Requirements: 12.1, 12.2, 12.3_
  - [x] 12.2 HTMX results partial in an `aria-live` region, 50 per page up to 2000, filtered rank numbers
    - _Requirements: 12.4, 12.5, 12.6_

- [x] 13. Building detail
  - [x] 13.1 `/town/building` with `_find_building`, 404, month dates, building-level address, rental-only history
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

- [x] 14. Inspection status
  - [x] 14.1 `building_status` table and `get_statuses`, `get_status`, `set_status`
    - _Requirements: 14.1_
  - [x] 14.2 `POST /town/building/status` with CSRF, value check, 404, HTMX partial or redirect
    - _Requirements: 14.2, 14.3, 14.4_
  - [x] 14.3 Text status pill and "doesn't change the building's scores or rank" note
    - _Requirements: 14.5_

- [x] 15. Accessibility and copy style
  - [x] 15.1 Labels, captions, `scope`, and `aria-live` regions on town templates
    - _Requirements: 15.1_
  - [x] 15.2 The em dash and exclamation point check in `tests/test_final_checks.py` renders the signed-in building detail and simulated detail pages
    - _Requirements: 15.2_

- [ ] 16. Keep signed-in dashboard HTML out of the htmx history cache
  - [ ] 16.1 In a browser, filter the dashboard and use "Show more", then confirm `localStorage` has no `htmx-history-cache` entry for town pages, and that it is cleared after sign-out
    - _Requirements: 4.3, 2.6_
  - [x] 16.2 `hx-history="false"` on every town template's `<body>`, and `"storage"` added to logout's `Clear-Site-Data` (`app/routers/town.py`)
    - _Requirements: 2.6, 4.3_
  - [x] 16.3 `tests/test_town_history.py`: signed-in, signed-out, and every town template disable history; public pages keep it; logout clears cache and storage
    - _Requirements: 2.6, 4.3_
