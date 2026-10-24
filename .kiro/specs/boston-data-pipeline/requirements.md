# Requirements: Boston data pipeline and address matching

## Introduction
This is a retroactive spec for code that already exists. It covers how TwoWaysOut downloads
Analyze Boston datasets, turns them into the read-only `data/boston.sqlite` database, matches a
typed address to a Boston building, and returns either building history (likely rentals only) or
area-level context. All rules in `.kiro/steering/project-rules.md` apply, in particular privacy
rules 1 (owner and contact field whitelists) and 2 (rentals-only building history).

Code covered: `scripts/fetch_boston.py`, `scripts/preprocess_boston.py`, `scripts/history.py`,
`scripts/lookup.py`, `scripts/build_data.sh`, `app/services/boston.py`,
`app/services/address.py`, `app/services/address_normalize.py`,
`app/services/fire_categories.py`. There is no `app/services/history.py`; history building lives
in `scripts/history.py` and history reading lives in `app/services/boston.py`.

## Requirement 1: Download raw datasets
**User story:** As the project owner, I want one command that downloads the five Analyze Boston
datasets, so I can rebuild the city data from scratch.

### Acceptance criteria
1.1 WHEN `python -m scripts.fetch_boston` runs with no arguments THE SYSTEM SHALL download all
five datasets (`sam`, `assessment`, `rentsmart`, `violations`, `permits`) to `data/raw/<name>.csv`.
1.2 WHEN dataset names are passed as arguments THE SYSTEM SHALL download only those datasets.
1.3 IF an argument is not a known dataset name THEN THE SYSTEM SHALL exit with a message listing
the valid names and SHALL NOT download anything.
1.4 WHEN Analyze Boston redirects to a signed S3 URL THE SYSTEM SHALL follow the redirect itself
and remove the explicit `:443` port so the signature stays valid.
1.5 WHILE a file is downloading THE SYSTEM SHALL write to a `.csv.part` file and SHALL replace
the final `.csv` only after the download finishes.
1.6 WHEN a fetch run finishes THE SYSTEM SHALL record today's date for each fetched dataset in
`data/raw/SNAPSHOT_DATES.json`, and SHALL write today's date to `data/raw/SNAPSHOT_DATE` only
when all five datasets were fetched in that run.
1.7 IF only some datasets are fetched THEN THE SYSTEM SHALL NOT record a snapshot date that is
newer than the oldest dataset that feeds `boston.sqlite`. Preprocessing SHALL use the oldest
per-dataset date, falling back to `SNAPSHOT_DATE` for datasets without one, then to today.
1.8 THE SYSTEM SHALL keep raw downloads only in `data/raw/`, which is gitignored and excluded
from the Docker build context and final image.

## Requirement 2: One-step build
**User story:** As the project owner, I want a single script that fetches and preprocesses, so
local builds and the Docker build use the same steps.

### Acceptance criteria
2.1 WHEN `scripts/build_data.sh` runs THE SYSTEM SHALL run `scripts.fetch_boston` with no
dataset arguments, then `scripts.preprocess_boston`, from the project root.
2.2 WHERE `--python <path>` is given THE SYSTEM SHALL use that interpreter; otherwise it SHALL
use `.venv/bin/python`.
2.3 IF any step fails or an unknown argument is given THEN THE SYSTEM SHALL stop with a non-zero
exit code (`set -euo pipefail`, exit 2 for bad arguments).
2.4 WHEN the Docker image is built THE SYSTEM SHALL run the build script, delete `data/raw` in
the same layer, and copy only `data/boston.sqlite` into the runtime image as read-only.
2.5 WHERE a Data Commons API key is available (`DATACOMMONS_API_KEY_FILE`,
`DATACOMMONS_API_KEY`, or `DATA_COMMONS_API_KEY`) THE SYSTEM SHALL run the optional
`scripts.fetch_datacommons` step between fetch and preprocess, and SHALL continue without area
housing data if that step fails or no key is set (see
`.kiro/specs/nearby-construction-and-census/`).

## Requirement 3: Owner and contact field whitelists (privacy rule 1)
**User story:** As a property owner or contact named in city records, I want my name and mailing
address never to reach the app, so the tool can't be used to look me up.

### Acceptance criteria
3.1 WHEN the SAM addresses file is read THE SYSTEM SHALL load only the columns in
`SAM_COLUMNS`.
3.2 WHEN the Property Assessment file is read THE SYSTEM SHALL load only the columns in
`ASSESSMENT_COLUMNS`, which SHALL NOT include `OWNER`, `MAIL_ADDRESSEE`, `MAIL_STREET_ADDRESS`,
`MAIL_CITY`, `MAIL_STATE`, or `MAIL_ZIP_CODE`.
3.3 WHEN the RentSmart file is read THE SYSTEM SHALL load only `RENTSMART_COLUMNS`, which SHALL
NOT include `owner`.
3.4 WHEN the building violations file is read THE SYSTEM SHALL load only `VIOLATION_COLUMNS`,
which SHALL NOT include `contact_addr1`, `contact_addr2`, `contact_city`, `contact_state`, or
`contact_zip`.
3.5 WHEN the building permits file is read THE SYSTEM SHALL load only `PERMIT_COLUMNS`, which
SHALL NOT include `applicant` or `comments`.
3.6 THE SYSTEM SHALL apply the whitelists at read time with `pandas.read_csv(usecols=...)` so
excluded fields are never in memory.
3.7 THE `boston.sqlite` database SHALL contain no owner, mailing, applicant, comment, or contact
column or value. `properties.owner_occupied` is a Y/N flag and is allowed.

## Requirement 4: Building-level address table
**User story:** As a student, I want my typed address to match the city's address list, so I see
records for the right building.

### Acceptance criteria
4.1 WHEN SAM rows are processed THE SYSTEM SHALL keep only rows with no unit, a parcel ID, and a
street name, one row per building-level address.
4.2 WHEN a SAM row is a number range THE SYSTEM SHALL store `number_from` and `number_to` from
`RANGE_FROM` and `RANGE_TO`; otherwise both SHALL be the numeric part of the street number.
4.3 IF `number_from` is greater than `number_to` THEN THE SYSTEM SHALL swap them.
4.4 IF a row has no usable street number THEN THE SYSTEM SHALL drop it.
4.5 THE SYSTEM SHALL store the street as a normalized `street_key` built with the same
`street_key()` function used at lookup time.
4.6 THE SYSTEM SHALL store parcel IDs as 10-digit zero-padded strings with any trailing `_`
removed, and ZIP codes as 5-digit strings.

## Requirement 5: Properties and rental detection
**User story:** As a student, I want to know whether a building is likely a rental, because
building history is only shown for rentals.

### Acceptance criteria
5.1 WHEN assessment rows are processed THE SYSTEM SHALL produce one `properties` row per building
parcel, rolling condo unit rows up to their condo main parcel (`CM_ID`).
5.2 WHEN land use is `R2`, `R3`, `R4`, `A`, or `RC` THE SYSTEM SHALL mark the building as a
likely rental with reason "multi-family building".
5.3 WHEN land use is `CM` THE SYSTEM SHALL mark the building as a rental only if at least one
`CD` unit is not owner-occupied, and SHALL mark it not a rental if it has no units or every unit
is owner-occupied.
5.4 WHEN land use is `R1` or `CD` THE SYSTEM SHALL mark the building as a rental only if
`OWN_OCC` is `N`.
5.5 WHEN land use is `E` or any other non-residential code THE SYSTEM SHALL mark the building as
not a rental.
5.6 THE SYSTEM SHALL store a plain-language `rental_reason` with every classification.
5.7 WHEN `RES_UNITS` is blank THE SYSTEM SHALL use the unit count implied by land use (`R1`=1,
`R2`=2, `R3`=3, `CD`=1); for `CM` it SHALL count the `CD` unit rows.
5.8 IF a year built or remodeled is outside 1700 to the current year THEN THE SYSTEM SHALL store
it as null. For condos, missing year built and heat type SHALL fall back to the most common unit
value, and year remodeled SHALL be the latest unit value.

## Requirement 6: Fire-related records and permits
**User story:** As a student, I want only fire-safety records, with readable descriptions, so the
history is relevant and easy to read.

### Acceptance criteria
6.1 WHEN a record description is categorized THE SYSTEM SHALL assign the first matching category
of `smoke_alarms`, `heating`, `egress`, `fire_protection`, `electrical`.
6.2 IF a description matches an exclusion pattern (utility metering, billing, shutoff, exhaust
outlets) or no category THEN THE SYSTEM SHALL drop the record.
6.3 WHEN RentSmart rows are read THE SYSTEM SHALL keep only Housing Violations, Enforcement
Violations (as "violation"), and Housing Complaints, Sanitation Requests, Civic Maintenance
Requests (as "complaint"), and SHALL skip "Building Violations" because the ISD dataset covers them.
6.4 WHEN an ISD violation is read THE SYSTEM SHALL map its `sam_id` (including unit-level SAM
IDs) to a parcel, and SHALL drop it if no parcel is found.
6.5 THE SYSTEM SHALL map every record and permit parcel to its building parcel so condo unit
records roll up to the building.
6.6 WHEN a description is stored THE SYSTEM SHALL cut it at the first legal reference (CMR,
M.G.L., section sign, section numbers, "required by") and limit it to 160 characters.
6.7 WHEN permits are read THE SYSTEM SHALL keep only fire alarm, sprinkler, and electrical
permits, matched by work type or permit type, with a parcel from `parcel_id` or `property_id`
and a valid issue date.

## Requirement 7: Rentals-only building history (privacy rule 2)
**User story:** As an owner-occupant, I want my home's record history not stored or shown at the
building level, because the tool is about rentals.

### Acceptance criteria
7.1 WHEN the `records` table is written THE SYSTEM SHALL include only rows whose building parcel
is a likely rental.
7.2 WHEN the `permits` table is written THE SYSTEM SHALL include only rows whose building parcel
is a likely rental.
7.3 WHEN a matched address is not a likely rental THE SYSTEM SHALL NOT return building history
and SHALL return area context instead, with a reason that says the building isn't listed as a
rental.
7.4 WHEN the town dashboard asks for a parcel's history THE SYSTEM SHALL return nothing unless
the parcel is a likely rental, even if records exist for that parcel.
7.5 THE `records` table SHALL NOT store ZIP or ward columns.

## Requirement 8: Area statistics
**User story:** As a student whose building has no building-level history, I want neighborhood
context, so I still have something to ask about.

### Acceptance criteria
8.1 WHEN area statistics are built THE SYSTEM SHALL count fire-related records from all
buildings, not only rentals.
8.2 THE SYSTEM SHALL produce one row per ZIP, one per ward, and one citywide row (`Boston`).
8.3 THE SYSTEM SHALL count only records dated within 12 months before the snapshot date, and
SHALL store that start date in `since`.
8.4 Each row SHALL include totals, violation and complaint counts, open violations, one count per
fire category, and the number of likely rental buildings in the area.
8.5 THE SYSTEM SHALL derive ward from the first two digits of the parcel ID, and a rental
building's ZIP from its primary SAM address.

## Requirement 9: Database output
**User story:** As the project owner, I want the database written safely, so the app never reads
a half-written file.

### Acceptance criteria
9.1 WHEN preprocessing writes the database THE SYSTEM SHALL write to `boston.sqlite.tmp` and
replace `boston.sqlite` only when complete.
9.2 THE SYSTEM SHALL create tables `addresses`, `properties`, `meta`, and, when history files are
present, `records`, `permits`, `area_stats`, and `construction`, plus `census_zip` when
`data/raw/datacommons.json` exists, with the indexes in design.md (`construction` and
`census_zip` are specified in `.kiro/specs/nearby-construction-and-census/`).
9.3 THE `meta` table SHALL store `snapshot_date` and the row count of each table.
9.4 IF `sam.csv` or `assessment.csv` is missing THEN THE SYSTEM SHALL exit with a message naming
the fetch command.
9.5 IF any history file is missing THEN THE SYSTEM SHALL still write `addresses`, `properties`,
and `meta`, and print the fetch command for the history files.

## Requirement 10: Address parsing and normalization
**User story:** As a student, I want to type an address the way I normally would, so I don't have
to match the city's format.

### Acceptance criteria
10.1 WHEN a street name is normalized THE SYSTEM SHALL uppercase it, remove `.`, `,`, `'`,
collapse spaces, abbreviate a leading direction, a leading `MOUNT`/`SAINT`, and the street suffix.
10.2 WHEN an address is parsed THE SYSTEM SHALL extract the house number or range, street key,
ZIP (including ZIP+4), and city or neighborhood.
10.3 WHEN an address includes a unit (`Apt`, `Unit`, `#`, `Fl`, a bare unit token like `3`,
`352-1`, `Bsmt`) THE SYSTEM SHALL drop the unit.
10.4 IF there is no house number THEN THE SYSTEM SHALL return no parsed address.
10.5 WHEN free text contains a street address THE SYSTEM SHALL find the first one that parses,
for use when the student leaves the address field blank.

## Requirement 11: Address matching
**User story:** As a student, I want an exact match when possible and a clear reason when there
isn't one, so I'm never shown the wrong building.

### Acceptance criteria
11.1 WHEN the street key and ZIP match and the house number falls inside a SAM number range THE
SYSTEM SHALL match, preferring an exact number match, then the primary address, then the
narrowest range.
11.2 IF no row matches and the typed street has no suffix THEN THE SYSTEM SHALL retry with any
suffix and report `match_type` "no_suffix".
11.3 IF several streets or ZIPs remain and no ZIP was given THEN THE SYSTEM SHALL filter by a
typed neighborhood, and IF still more than one remains THEN THE SYSTEM SHALL return "ambiguous"
with the candidate ZIPs instead of guessing.
11.4 IF the ZIP, or the place when no ZIP is given, is not in Boston's address list THEN THE
SYSTEM SHALL return "outside_boston".
11.5 IF there is no house number THEN THE SYSTEM SHALL return "no_number"; IF nothing matches
THEN "not_found"; IF the database file is missing THEN "data_unavailable".
11.6 WHEN matching fails THE SYSTEM SHALL return a result with a plain-language reason and SHALL
NOT raise an exception.
11.7 THE SYSTEM SHALL open `boston.sqlite` read-only and use parameterized queries.

## Requirement 12: Building or area context for a report
**User story:** As a student, I want the report to show the right kind of Boston context for my
address.

### Acceptance criteria
12.1 IF the address is blank THEN THE SYSTEM SHALL return no context.
12.2 WHEN the address matches a likely rental THE SYSTEM SHALL return building history: counts
per category (violations, complaints, open), the 8 most recent records, permit summaries by kind,
total and open counts, first record date, and snapshot date.
12.3 WHEN the address matches a building that is not a likely rental THE SYSTEM SHALL return ZIP
area stats, falling back to ward stats, plus citywide stats.
12.4 WHEN a Boston address can't be matched and a ZIP was typed THE SYSTEM SHALL return that
ZIP's area stats with the no-match reason.
12.5 IF the address is outside Boston, ambiguous without area data, or has no area row THEN THE
SYSTEM SHALL return kind "none" with a reason (and candidate ZIPs when ambiguous).
12.6 IF the database is missing or has no history tables THEN THE SYSTEM SHALL return kind
"none" with a reason that Boston data isn't loaded.
12.7 THE SYSTEM SHALL NOT present area statistics as information about the building.

## Requirement 13: Town dashboard support
**User story:** As a town user, I want official history for a ranked rental parcel and the data
snapshot date.

### Acceptance criteria
13.1 WHEN the dashboard asks for a parcel's history THE SYSTEM SHALL use the parcel's primary
city address for display and SHALL NOT need a typed address.
13.2 IF the parcel is empty, the database is missing, or history tables are missing THEN THE
SYSTEM SHALL return nothing.
13.3 WHEN the snapshot date is requested THE SYSTEM SHALL return it from `meta`, or nothing if
the database is missing, unreadable, or has no snapshot row.

## Requirement 14: Command-line lookup
**User story:** As the developer, I want to check an address from the terminal.

### Acceptance criteria
14.1 WHEN `python -m scripts.lookup "<address>"` runs THE SYSTEM SHALL print the match type,
address, SAM ID, parcel, ward, land use, units, rental status and reason, year built,
remodel year, and heat type.
14.2 IF there is no match THEN THE SYSTEM SHALL print the reason and any candidate ZIPs.
14.3 IF no address is given THEN THE SYSTEM SHALL exit with a usage message.
