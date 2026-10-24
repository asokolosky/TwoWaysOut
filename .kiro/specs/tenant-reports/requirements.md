# Requirements: Anonymous tenant hazard reports

## Introduction

This is a retroactive spec for the existing tenant report feature. Tenants can report a
fire-safety problem at a rental building without giving any personal details. Reports are saved
to the `reports` table in `data/app.sqlite` and feed the town dashboard ranking. A separate
script seeds fictional reports into `simulated_reports` for the demo.

Code covered: `app/routers/report.py`, `app/services/reports.py`, `app/services/rate_limit.py`,
`app/content/report_categories.py`, `app/db.py`, `app/templates/report_form.html`,
`app/templates/report_thanks.html`, and `scripts/seed_reports.py`. All rules in
`.kiro/steering/project-rules.md` apply. The town dashboard itself is out of scope except where it
reads reports.

## Requirement 1: Anonymous report form

**User story:** As a tenant, I want to report a fire-safety problem without identifying myself,
so I can warn the town without risk to my tenancy.

### Acceptance criteria

1.1 WHEN a client requests `GET /report` THE SYSTEM SHALL render a form with a building address
field, one checkbox per entry in `REPORT_CATEGORIES`, an optional details field, an optional
"When did you notice it?" date field, and a hidden honeypot field named `website`.
1.2 THE SYSTEM SHALL NOT include any name, email, phone, or account field in the form, and the
`reports` table SHALL have no such columns.
1.3 WHEN `GET /report` includes an `address` query parameter THE SYSTEM SHALL prefill the
address field with that value, cut to 200 characters and HTML-escaped.
1.4 WHEN the form is rendered THE SYSTEM SHALL show a notice to call 911 for a fire or immediate
danger, and a statement that reports are anonymous and IP addresses are not stored.
1.5 WHEN the form is rendered THE SYSTEM SHALL give every input a label, describe each checkbox
with its category hint through `aria-describedby`, and group the checkboxes in a `fieldset`
with a legend and the help text "Check all that apply."

## Requirement 2: Address validation

**User story:** As a town inspector, I want each report tied to a building address, so reports
for the same building can be grouped.

### Acceptance criteria

2.1 WHEN a report is submitted THE SYSTEM SHALL collapse runs of whitespace in the address
before validating it.
2.2 IF the address is empty THEN THE SYSTEM SHALL reject the report with "Enter the address of
the building."
2.3 IF the address is longer than 200 characters THEN THE SYSTEM SHALL reject the report with
"That address is too long."
2.4 IF the address contains an email address or phone number THEN THE SYSTEM SHALL reject the
report with "Leave contact information out of the address." and SHALL NOT edit the address.
2.5 IF the address has no parseable street number and street THEN THE SYSTEM SHALL reject the
report and ask for the street number.
2.6 WHEN the address matches a Boston parcel THE SYSTEM SHALL store the parcel ID, SAM ID, ward,
ZIP, and official display address, and set `address_key` to `PARCEL <parcel_id>`.
2.7 WHEN the address does not match a Boston parcel THE SYSTEM SHALL store a building-level
`address_key` of "NUMBER STREET ZIP" (or place when there is no ZIP), with unit numbers dropped,
and the ZIP parsed from the typed address.

## Requirement 3: Multiple problems per report

**User story:** As a tenant, I want to check every problem I see, and as a town, I want one
report to count once, so checking every box can't inflate a building's rank.

### Acceptance criteria

3.1 WHEN a report is submitted THE SYSTEM SHALL accept one or more `category` values and drop
duplicates.
3.2 IF no category is selected, or any selected value is not a key in `REPORT_CATEGORIES`, THEN
THE SYSTEM SHALL reject the report with "Choose what kind of problem you're reporting."
3.3 IF the request contains more `category` values than there are categories THEN THE SYSTEM
SHALL reject the report with the same message.
3.4 WHEN a report is saved THE SYSTEM SHALL order the selected categories by severity, highest
first, breaking ties by their order in `REPORT_CATEGORIES`.
3.5 WHEN a report is saved THE SYSTEM SHALL store the most serious category in
`reports.category` and the others, comma-separated, in `reports.extra_categories` (NULL when
there are none).
3.6 WHEN real buildings are ranked THE SYSTEM SHALL score each report once, at the severity of
`reports.category`, and SHALL use `extra_categories` only for hazard labels and category filters.
3.7 THE SYSTEM SHALL use these severities: no second way out 5, smoke or CO alarm 5, blocked exit
4, electrical 4, heating 3, other 1.

## Requirement 4: Contact information redaction

**User story:** As a tenant, I want any contact details I type by mistake removed, so my report
stays anonymous.

### Acceptance criteria

4.1 WHEN a description is saved THE SYSTEM SHALL replace email addresses, including spaced
("jane @ umass.edu") and spelled-out ("jane at umass dot edu") forms with a common TLD, with
`[email removed]` before the description is written to the database.
4.2 WHEN a description is saved THE SYSTEM SHALL replace North American phone numbers, 7-digit
local numbers with a `-` or `.` separator, and `+` international numbers with at least 8 digits
with `[phone removed]` before the description is written to the database.
4.3 WHEN a description is saved THE SYSTEM SHALL replace social handles such as `@jane_doe` with
`[handle removed]`.
4.4 THE SYSTEM SHALL leave ordinary text unchanged, including years, street numbers, unit
numbers, ISO dates, ZIP+4 codes, number ranges, and phrases like "the alarm at the front door".
4.5 WHEN any contact information was removed THE SYSTEM SHALL tell the tenant on the
confirmation page.
4.6 IF the trimmed description is longer than 1,000 characters THEN THE SYSTEM SHALL reject the
report with "Keep the description under 1,000 characters."
4.7 WHEN the description is empty after trimming THE SYSTEM SHALL store NULL.

## Requirement 5: Dates

**User story:** As a town inspector, I want to know when a problem was seen, without dates that
could be matched to a log line.

### Acceptance criteria

5.1 WHEN an observed date is given THE SYSTEM SHALL accept only `YYYY-MM-DD` and store it in
that form.
5.2 IF the observed date is not a valid ISO date THEN THE SYSTEM SHALL reject the report with
"Enter the date as YYYY-MM-DD, or leave it blank."
5.3 IF the observed date is after today THEN THE SYSTEM SHALL reject it as in the future.
5.4 IF the observed date is before 2000-01-01 THEN THE SYSTEM SHALL reject it as too far in the
past.
5.5 WHEN a report is saved THE SYSTEM SHALL set `created_at` explicitly to today's date at day
precision, even if the table's default is a full timestamp.

## Requirement 6: Storage and schema

**User story:** As the project owner, I want reports in a simple local table that upgrades
itself, so older databases keep working.

### Acceptance criteria

6.1 WHEN the app database is first used in a process, or the file was deleted, THE SYSTEM SHALL
apply the schema in `app/db.py` with `CREATE TABLE IF NOT EXISTS`.
6.2 WHEN the `reports` table has no `extra_categories` column THE SYSTEM SHALL add it with
`ALTER TABLE`, and SHALL ignore a "duplicate column" error from a concurrent process.
6.3 WHEN a user submission is saved THE SYSTEM SHALL always write `is_simulated = 0`, set in the
SQL statement and not taken from the request.
6.4 THE SYSTEM SHALL constrain `reports.is_simulated` to 0 or 1 and `reports.status` to `open`,
`scheduled`, or `inspected`, with `status` defaulting to `open`.
6.5 WHILE the ranking service reads a database that lacks `extra_categories` THE SYSTEM SHALL
read it as NULL instead of failing, since ranking opens the database read-only.
6.6 WHEN `save_report` or `count_reports` finishes, including on error, THE SYSTEM SHALL close
its SQLite connection explicitly (`contextlib.closing`), and `save_report` SHALL commit before
closing.

## Requirement 7: Rate limiting and client IPs

**User story:** As the project owner, I want to limit floods of reports without keeping any
record of who sent them.

### Acceptance criteria

7.1 WHEN a report is submitted THE SYSTEM SHALL allow at most `reports_per_hour` submissions
(default 5) per client IP in a sliding one-hour window.
7.2 IF the limit is reached THEN THE SYSTEM SHALL return status 429 with the form, the typed
values, and "You've sent several reports in the last hour. Please try again later."
7.3 THE SYSTEM SHALL use client IPs only in memory for rate limiting, keyed by an HMAC-SHA256 of
the IP under a random per-process salt, and SHALL NOT store IPs in any database or file.
7.4 THE SYSTEM SHALL NOT log client IPs, and SHALL disable the uvicorn access log at import and
in the container entrypoint.
7.5 WHEN 500 limiter calls have passed, or the limiter holds 10,000 keys, THE SYSTEM SHALL drop
keys whose newest hit is outside the window.
7.6 WHEN `reports_per_hour` changes THE SYSTEM SHALL build a new limiter with the new limit.
7.7 IF a submission is rejected with a `ReportError` (nothing saved) THEN THE SYSTEM SHALL refund
its hit, so fixing a typo doesn't use up the hourly limit. Once the limit is reached, the 429
still applies before validation.
7.8 WHEN the app runs behind a proxy THE SYSTEM SHALL take the client IP from `X-Forwarded-For`
only from addresses in `FORWARDED_ALLOW_IPS` (default `127.0.0.1`), never from every peer.

## Requirement 8: Bot honeypot

**User story:** As the project owner, I want simple bots ignored without tipping them off.

### Acceptance criteria

8.1 IF the hidden `website` field is filled THEN THE SYSTEM SHALL show the normal confirmation
page and SHALL NOT save the report.
8.2 THE SYSTEM SHALL hide the honeypot field from people and screen readers (`aria-hidden="true"`,
`tabindex="-1"`).

## Requirement 9: Confirmation page

**User story:** As a tenant, I want to know my report was received and what to do next.

### Acceptance criteria

9.1 WHEN a report is saved THE SYSTEM SHALL show the problem labels most serious first, the
building (official address when matched, otherwise a note that it was recorded as typed), and
the department that usually handles the most serious problem.
9.2 WHEN the address matched Boston, or the lookup reason was `not_found` or `ambiguous`, THE
SYSTEM SHALL link Boston 311 and Inspectional Services, with "(opens in a new tab)" screen-reader
text.
9.3 WHEN the report is outside Boston THE SYSTEM SHALL tell the tenant to contact the town's
Board of Health or building department.
9.4 WHEN the confirmation page is shown THE SYSTEM SHALL say that TwoWaysOut doesn't send
inspectors or contact landlords, show the 911 notice, and include the standard disclaimer.

## Requirement 10: Error handling

**User story:** As a tenant, I want clear errors that keep what I typed.

### Acceptance criteria

10.1 IF validation fails THEN THE SYSTEM SHALL return status 422 with the form, the error in a
`role="alert"` element, and the typed address, description, and date.
10.2 WHEN the form is re-rendered after an error THE SYSTEM SHALL re-check only boxes whose
values are known category IDs, and SHALL NOT echo unknown values.
10.3 IF a field exceeds its hard cap (address 2,000, description 10,000, date 200 characters)
THEN THE SYSTEM SHALL return the form with "Some of what you entered is too long. Please shorten
it and try again." and SHALL NOT echo the submitted values.
10.4 WHEN user text is rendered THE SYSTEM SHALL HTML-escape it.

## Requirement 11: Simulated reports seed

**User story:** As the presenter, I want realistic demo reports that can't point to any real
building.

### Acceptance criteria

11.1 THE SYSTEM SHALL store simulated reports only in `simulated_reports`, which has no address,
parcel, SAM ID, or ZIP columns, only a synthetic `sim_building` ID, ward, and rental type.
11.2 WHEN `scripts/seed_reports.py` runs THE SYSTEM SHALL delete all rows in
`simulated_reports` and insert 40 rows across 14 buildings `SIM-01` to `SIM-14`, using a fixed
random seed.
11.3 WHEN the seed script runs THE SYSTEM SHALL NOT read or write the `reports` table.
11.4 WHEN `boston.sqlite` is available THE SYSTEM SHALL choose (ward, rental type) labels only
from aggregate counts of likely rentals, and SHALL use only groups with at least `MIN_GROUP_SIZE`
(20) likely rentals, checked in SQL and again after mapping land uses to rental types.
11.5 IF `boston.sqlite` is missing or unreadable THEN THE SYSTEM SHALL use the built-in
`FALLBACK_COMBOS` list.
11.6 IF fewer than 14 real groups qualify THEN THE SYSTEM SHALL top up from `FALLBACK_COMBOS`,
skipping any pair that matches a real group below `MIN_GROUP_SIZE`.
11.7 WHEN the seed script builds rows THE SYSTEM SHALL use only fictional descriptions that start with "Simulated report:",
and SHALL assert that each one passes contact redaction unchanged and uses a valid category.
11.8 WHEN the container starts with `SEED_SIMULATED=1` and `simulated_reports` is missing or
empty THE SYSTEM SHALL run the seed script.

## Requirement 12: Simulated reports never affect real rankings

**User story:** As a town, I want real rankings to come only from real reports and official
records.

### Acceptance criteria

12.1 WHEN real buildings are ranked THE SYSTEM SHALL read only `reports WHERE is_simulated = 0`
and SHALL NOT read `simulated_reports`.
12.2 WHEN simulated buildings are ranked THE SYSTEM SHALL read only `simulated_reports`.
12.3 WHEN a tenant submits a report THE SYSTEM SHALL NOT read or change `simulated_reports`.
