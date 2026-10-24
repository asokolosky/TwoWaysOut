# Requirements: Town dashboard and building ranking

## Introduction

This is a retroactive spec for the town dashboard that already exists in TwoWaysOut. Town and
city staff sign in with a shared password and see real buildings ranked by reported
fire-safety problems, a separate SIMULATED section of masked demo data, a detail page per
building, and an inspection status workflow (open, scheduled, inspected).

Code covered: `app/routers/town.py`, `app/services/ranking.py`, `app/services/building_status.py`,
`app/services/town_auth.py`, the `SecurityHeaders` middleware in `app/main.py`, the settings in
`app/config.py`, the town tables in `app/db.py`, `app/content/copy.py`,
`app/content/report_categories.py`, and the `town_*` templates. All rules in
`.kiro/steering/project-rules.md` apply.

## Requirement 1: Closed unless configured, password sign-in

**User story:** As the project owner, I want the dashboard to stay closed until it has a
password and a session secret, so it never opens to the public by accident.

### Acceptance criteria

1.1 IF `DASHBOARD_PASSWORD` is unset or `SESSION_SECRET` is unset or shorter than 32 characters
THEN THE SYSTEM SHALL answer every `/town` route with HTTP 503 and the "Dashboard isn't
configured" page, and SHALL NOT set a session cookie.
1.2 WHEN a visitor without a valid session requests a town page THE SYSTEM SHALL redirect to
`/town/login` with HTTP 303.
1.3 WHEN the unauthenticated request is an HTMX request THE SYSTEM SHALL return HTTP 200 with an
`HX-Redirect: /town/login` header instead of swapping in a login form.
1.4 WHEN a signed-in user opens `/town/login` THE SYSTEM SHALL redirect to `/town`.
1.5 WHEN a password is submitted THE SYSTEM SHALL compare SHA-256 digests of the supplied and
expected passwords with `hmac.compare_digest`, SHALL NOT trim whitespace, and SHALL never match
an empty expected password.
1.6 IF the password is wrong THEN THE SYSTEM SHALL return HTTP 401 with "That password isn't
right." and SHALL NOT echo the submitted value.
1.7 WHEN a client IP has used 5 sign-in attempts in 15 minutes THE SYSTEM SHALL return HTTP 429
with "Too many sign-in attempts. Please wait 15 minutes and try again."
1.8 WHEN a sign-in succeeds THE SYSTEM SHALL refund the reserved attempt, so only failures count
toward the limit.
1.9 THE SYSTEM SHALL reserve an attempt before checking the password, so concurrent guesses
can't exceed the limit.
1.10 THE SYSTEM SHALL use the client IP only in memory, hashed with HMAC, and SHALL NOT store or
log it.
1.11 THE SYSTEM SHALL NOT include the dashboard password in any response, cookie, or token.

## Requirement 2: Signed sessions and sign-out

**User story:** As a town staff member, I want a session that expires and that really ends when
I sign out, so a copied cookie can't be reused.

### Acceptance criteria

2.1 WHEN a sign-in succeeds THE SYSTEM SHALL issue a token `<issued_at>.<nonce>.<signature>`
where the signature is HMAC-SHA256 over `session|<issued_at>|<nonce>` with `SESSION_SECRET`
and the nonce is `secrets.token_urlsafe(24)`.
2.2 THE SYSTEM SHALL set the token in cookie `tw_town_session` with `Path=/town`, `HttpOnly`,
`SameSite=Lax`, and `Max-Age` of 8 hours.
2.3 WHEN the request scheme is `https` or WHERE `force_secure_cookies` is true THE SYSTEM SHALL
mark the cookie `Secure`. `force_secure_cookies` SHALL default to false.
2.4 IF a token is missing, longer than 256 characters, non-ASCII, malformed, wrongly signed,
issued more than 60 seconds in the future, or 8 hours old or older THEN THE SYSTEM SHALL treat
the request as signed out.
2.5 WHEN `SESSION_SECRET` changes THE SYSTEM SHALL reject cookies signed with the old secret.
2.6 WHEN a signed-in user signs out with a valid CSRF token THE SYSTEM SHALL record the nonce in
`revoked_sessions` with `expires_at = issued_at + 8 hours`, delete expired rows, delete the
cookie, send `Clear-Site-Data: "cache", "storage"`, and redirect to `/town/login`.
2.7 IF a session's nonce is in `revoked_sessions` THEN THE SYSTEM SHALL treat the request as
signed out.
2.8 WHEN one session signs out THE SYSTEM SHALL leave other sessions valid.
2.9 IF sign-out fails the CSRF check THEN THE SYSTEM SHALL return HTTP 403 and SHALL NOT send
`Clear-Site-Data`.

## Requirement 3: CSRF protection

**User story:** As a town staff member, I want state-changing actions to need a token tied to my
session, so another site can't change statuses or sign me out.

### Acceptance criteria

3.1 THE SYSTEM SHALL derive the CSRF token as HMAC-SHA256 over `csrf|<nonce>` and render it into
every signed-in page.
3.2 WHEN `POST /town/logout` or `POST /town/building/status` is received THE SYSTEM SHALL accept
the token from the `csrf_token` form field or the `X-CSRF-Token` header.
3.3 IF the token is missing, non-ASCII, from another session, or not an exact match THEN THE
SYSTEM SHALL return HTTP 403 with "This form expired. Reload the page and try again."

## Requirement 4: Response headers for town pages

**User story:** As the project owner, I want signed-in pages kept out of caches and building
keys kept out of referrers.

### Acceptance criteria

4.1 WHEN a response is for `/town` or a path under `/town/` THE SYSTEM SHALL send
`Cache-Control: no-store`, `Pragma: no-cache`, and `Referrer-Policy: no-referrer`, including on
redirects and the login page.
4.2 THE SYSTEM SHALL send `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and the
app's `Content-Security-Policy` on every response.
4.3 THE SYSTEM SHALL set `hx-history="false"` on the `<body>` of every town template
(`town_login.html`, `town_dashboard.html`, `town_building.html`, `town_simulated.html`,
`town_not_found.html`, `town_not_configured.html`), so htmx never saves a town page snapshot to
`localStorage`. Public pages keep htmx history.

## Requirement 5: Ranking statement

**User story:** As a town inspector, I want the dashboard to say what the ranking means, so I
don't read it as a fire-risk prediction.

### Acceptance criteria

5.1 THE SYSTEM SHALL define `RANKING_STATEMENT` in `app/content/copy.py` as exactly
"Rankings reflect reported problems, not predicted fire risk".
5.2 WHEN the dashboard or a building detail page is shown THE SYSTEM SHALL display that exact
string.
5.3 THE SYSTEM SHALL state on the dashboard that a low score doesn't mean a building is safe.

## Requirement 6: Tenant score

**User story:** As a town inspector, I want recent, serious tenant reports to count most.

### Acceptance criteria

6.1 THE SYSTEM SHALL compute each report's weight as severity x `0.5 ** (age_days / 90)`, a
90-day half-life.
6.2 THE SYSTEM SHALL use these severities from `app/content/report_categories.py`:

| Category id | Label | Severity |
|---|---|---|
| `no_second_exit` | No second way out | 5 |
| `smoke_alarm` | Missing or broken smoke or carbon monoxide alarm | 5 |
| `blocked_exit` | Blocked exit or stairway | 4 |
| `electrical_hazard` | Electrical hazard | 4 |
| `heating_hazard` | Heating problem | 3 |
| `other` | Other fire-safety problem | 1 |

6.3 WHEN a report has an observed date THE SYSTEM SHALL measure age from it, otherwise from
`created_at`, reading dates at day precision.
6.4 WHEN a report is dated in the future THE SYSTEM SHALL count it at full weight.
6.5 THE SYSTEM SHALL score each report once, at its most serious category (`reports.category`),
even when several problems were selected.
6.6 THE SYSTEM SHALL use the other selected categories (`reports.extra_categories`) only for
hazard labels and the problem filter.
6.7 THE SYSTEM SHALL set a building's tenant score to the sum of its report weights.
6.8 IF a category id is unknown THEN THE SYSTEM SHALL score it as `other`.

## Requirement 7: Official score

**User story:** As a town inspector, I want open city violations and recent city records to
count, without letting them swamp tenant reports.

### Acceptance criteria

7.1 THE SYSTEM SHALL compute official score as min(10, open fire-related violations x 3 +
fire-related records in the last 12 months x 1).
7.2 THE SYSTEM SHALL measure the 12-month window back from the Boston snapshot date in the
`meta` table, not from today. WHEN the snapshot date is February 29 THE SYSTEM SHALL start the
window on February 28.
7.3 THE SYSTEM SHALL count a record as an open violation only when `kind = 'violation'` and
`status = 'Open'`.
7.4 THE SYSTEM SHALL use official records only for parcels with `properties.is_rental = 1`.
7.5 WHEN a parcel isn't a likely rental THE SYSTEM SHALL give it official score 0, no parcel ID,
and a normalized building-level address instead of the city's address.
7.6 WHEN a likely-rental parcel has official score above 0 and no tenant reports THE SYSTEM
SHALL still list it.
7.7 IF the Boston database, its `records` or `properties` table, or its snapshot date is missing
THEN THE SYSTEM SHALL rank tenant reports alone with official score 0.

## Requirement 8: Total, separate parts, and order

**User story:** As a town inspector, I want to see where a score comes from.

### Acceptance criteria

8.1 THE SYSTEM SHALL compute total score as tenant score + official score.
8.2 WHEN the ranked list or a building detail page is shown THE SYSTEM SHALL show tenant score,
official score, and total in separate columns or panels.
8.3 WHEN a building detail page is shown THE SYSTEM SHALL show the open violation count and the
12-month record count behind the official score.
8.4 THE SYSTEM SHALL order buildings by total descending, then tenant score descending, then
latest activity descending, then display address ascending, then building key ascending.
8.5 THE SYSTEM SHALL show up to 3 top hazard labels per building, ordered by their weighted
contribution.
8.6 THE SYSTEM SHALL explain both formulas, the half-life, and the cap in a "How scores work"
section on the dashboard.

## Requirement 9: Excluded ranking inputs

**User story:** As the project owner, I want rankings based only on reports and records, so the
dashboard doesn't steer inspections by neighborhood or who lives there.

### Acceptance criteria

9.1 THE SYSTEM SHALL NOT use building age, ZIP code, neighborhood, demographics, area
statistics (`area_stats`), Census or Data Commons data (`census_zip`), or nearby construction as
ranking inputs, and `app/services/ranking.py` SHALL NOT import the census or construction
services.
9.2 WHERE ZIP, ward, or neighborhood are shown THE SYSTEM SHALL use them only for display and
the ZIP filter.
9.3 THE SYSTEM SHALL NOT use inspection status as a ranking input.

## Requirement 10: Real ranking reads only real reports

**User story:** As the project owner, I want demo data never to change a real building's rank.

### Acceptance criteria

10.1 THE SYSTEM SHALL read tenant reports for the real ranking and building detail only with
`reports WHERE is_simulated = 0`.
10.2 THE SYSTEM SHALL NOT read `simulated_reports` in the real ranking.
10.3 WHEN simulated rows are added THE SYSTEM SHALL produce the same real ranking as before.
10.4 THE SYSTEM SHALL open the app and Boston databases read-only for ranking and detail reads.

## Requirement 11: Separate, masked SIMULATED section

**User story:** As a presenter, I want to show how reports look without tying fake data to a
real building.

### Acceptance criteria

11.1 THE SYSTEM SHALL rank simulated buildings only against each other, from `simulated_reports`
only, with the same tenant formula.
11.2 THE SYSTEM SHALL show them in their own section headed "Simulated tenant reports" with a
"SIMULATED" badge on the heading, every row, and every report, plus a banner saying they are
not real buildings and not part of the ranking above.
11.3 THE SYSTEM SHALL label each simulated building as "Simulated report · Ward N · rental type"
and SHALL NOT expose address, parcel, SAM ID, or ZIP fields.
11.4 WHEN `/town/simulated/{id}` is requested THE SYSTEM SHALL accept only IDs matching
`SIM-[A-Za-z0-9_-]{1,40}` that exist, and otherwise return HTTP 404.
11.5 THE SYSTEM SHALL show simulated report dates by month only.
11.6 WHEN any filter is applied THE SYSTEM SHALL NOT show simulated rows in the real results.

## Requirement 12: Filters and paging

**User story:** As a town inspector, I want to narrow the list by ZIP or problem type.

### Acceptance criteria

12.1 WHEN a ZIP filter is given THE SYSTEM SHALL accept only 5 digits. IF it isn't 5 digits
THEN THE SYSTEM SHALL ignore it and show "Enter a 5-digit ZIP code." in an alert.
12.2 WHEN a problem filter is given THE SYSTEM SHALL accept tenant category ids and Boston fire
categories (labeled "(any source)"), and SHALL ignore unknown values.
12.3 WHEN a Boston fire category is chosen THE SYSTEM SHALL match tenant reports linked to it and
official records in it with an open or recent count.
12.4 WHEN the filter form is submitted with HTMX targeting `town-results` THE SYSTEM SHALL return
only the results partial, inside an `aria-live="polite"` region.
12.5 THE SYSTEM SHALL show 50 buildings by default, with a "Show more buildings" link adding 50,
up to 2000.
12.6 THE SYSTEM SHALL keep the rank numbers from the filtered list.

## Requirement 13: Building detail

**User story:** As a town inspector, I want one page per building with its reports and records.

### Acceptance criteria

13.1 WHEN `/town/building?key=...` names a building in the current ranking THE SYSTEM SHALL show
its rank, score parts, inspection status, real tenant reports newest first, and official
records. IF it doesn't THEN THE SYSTEM SHALL return HTTP 404.
13.2 THE SYSTEM SHALL show tenant report dates by month only.
13.3 THE SYSTEM SHALL NOT display a tenant's typed `address_input`. Buildings without a city
address SHALL show a normalized building-level address, or "Address not recognized".
13.4 WHEN the building is a likely rental with a parcel ID THE SYSTEM SHALL show official
history. Otherwise THE SYSTEM SHALL say official records aren't shown for it.
13.5 THE SYSTEM SHALL HTML-escape report descriptions.

## Requirement 14: Inspection status

**User story:** As a town inspector, I want to mark a building open, scheduled, or inspected.

### Acceptance criteria

14.1 THE SYSTEM SHALL store one status per building key in `building_status`, one of `open`,
`scheduled`, `inspected`, with an `updated_on` day. Buildings without a row SHALL show "Open".
14.2 WHEN a valid status is posted with a valid CSRF token for a building in the ranking THE
SYSTEM SHALL save it. WHEN the request is HTMX THE SYSTEM SHALL return the status partial with
"Status saved.", otherwise redirect to the detail page.
14.3 IF the status isn't exactly one of the three values THEN THE SYSTEM SHALL return HTTP 422
with "Choose open, scheduled, or inspected." IF the building isn't in the ranking THEN THE
SYSTEM SHALL return HTTP 404.
14.4 WHEN a GET request is made THE SYSTEM SHALL NOT change any status.
14.5 THE SYSTEM SHALL show status as a text label, not color alone, and say it doesn't change
scores or rank.

## Requirement 15: Accessibility

### Acceptance criteria

15.1 THE SYSTEM SHALL label every form input, use table captions and `scope` attributes, and wrap
HTMX-updated content in `aria-live="polite"` regions.
15.2 THE SYSTEM SHALL keep em dashes and exclamation points out of town page text, including the
login, dashboard, building detail, and simulated detail pages.
