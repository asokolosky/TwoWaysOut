# Requirements: Nearby construction and area housing (Census) cards

## Introduction

This is a retroactive spec for two context cards on the student report: "Construction nearby"
and "Area housing (U.S. Census via Data Commons)". The construction card uses Boston's approved
building permits, reduced at build time to block-level sites. The census card uses U.S. Census
American Community Survey figures by ZIP code, fetched from Data Commons at build time for a fixed
list of ZIPs. Neither card is a ranking input.

Code covered: `scripts/construction.py`, `app/services/construction.py`,
`app/services/building_questions.py` (`construction_questions`),
`app/templates/partials/construction_card.html`, `scripts/fetch_datacommons.py`,
`app/services/census.py`, `app/templates/partials/census_card.html`, the `construction` and
`census_zip` parts of `scripts/preprocess_boston.py`, `scripts/build_data.sh`,
`app/routers/check.py` (`_area_context`), and `app/content/sources.py` (`nfpa_construction`).
All rules in `.kiro/steering/project-rules.md` apply, in particular privacy rules 7 and 8, the
approved data sources list, and the note on Boston's OpenContext MCP.

## Requirement 1: Construction permit classification

**User story:** As a student, I want to know about large construction projects near a rental, so
I can ask how the site affects the building's fire safety.

### Acceptance criteria

1.1 WHEN a permit has permit type "Erect/New Construction" or "Foundation Permit", or worktype
`ERECT`, THE SYSTEM SHALL classify it as `new_construction`, labeled "Foundation for a new
building" for foundation permits and "New building" otherwise.

1.2 WHEN a permit is a "Long Form/Alteration Permit" with worktype `ADDITION`, `INTEXT`,
`INTREN`, `EXTREN`, or `COB` and a declared value of at least $100,000 THE SYSTEM SHALL classify
it as `major_work` with the matching work label.

1.3 WHEN a permit has worktype `RAZE` THE SYSTEM SHALL classify it as `major_work` labeled
"Demolition", whatever its permit type or value.

1.4 IF a permit matches none of 1.1 to 1.3, or its declared value is missing or unparseable for
a long-form permit, THEN THE SYSTEM SHALL leave it out.

1.5 THE SYSTEM SHALL only include permits issued in the 24 months up to and including the
snapshot date.

## Requirement 2: Construction data privacy

**User story:** As a property owner or neighbor, I want permit data shown without exact
addresses or personal details, so the app can't be used to locate or identify me.

### Acceptance criteria

2.1 THE SYSTEM SHALL read permits only through the `CONSTRUCTION_COLUMNS` whitelist
(`permitnumber`, `worktype`, `permittypedescr`, `declared_valuation`, `issued_date`, `status`,
`address`, `property_id`, `parcel_id`, `y_latitude`, `x_longitude`), and SHALL never load
`applicant`, `comments`, `description`, or `total_fees`.

2.2 THE SYSTEM SHALL use `declared_valuation` only to filter permits and SHALL NOT store it in
the `construction` table.

2.3 THE SYSTEM SHALL store each site with a block label ("1-99 block of Boardman St", "100 block
of London St") and SHALL NOT store the house number, the full address, or the permit number.

2.4 IF an address contains a fraction or `#`, a second number, a joiner (`&`, AND, TO, THRU,
THROUGH, REAR, FRONT), a unit word (UNIT, APT, STE, FL, BSMT, RM and similar), a non-ordinal
number after the street start, a trailing ZIP, a street ending in a number, or a single-letter
unit before the street name THEN THE SYSTEM SHALL refuse to make a block label and leave the
site out.

2.5 THE SYSTEM SHALL keep letter suffixes, ranges, numbered streets ("5th St"), and lettered
streets ("B St") working, and the label SHALL never contain the original house number or either
end of a range.

2.6 THE SYSTEM SHALL round stored coordinates to 4 decimal places (about 11 m) and keep only
points inside Boston's bounding box.

2.7 THE SYSTEM SHALL store one row per site (building parcel, or rounded point when no parcel),
keeping the most significant kind and then the most recent permit.

## Requirement 3: Nearby search

**User story:** As a student, I want to see construction close to the address I checked, so the
list is relevant to that building.

### Acceptance criteria

3.1 WHEN a Boston address is matched with coordinates THE SYSTEM SHALL find sites within 250 m,
using a bounding box in SQL and then a haversine distance check, nearest first, up to 8 sites.

3.2 THE SYSTEM SHALL exclude the matched address's own parcel and its building parcel, and SHALL
exclude parcel-less sites within 10 m of the matched point.

3.3 WHEN several sites on the same block share a work label THE SYSTEM SHALL show only the
nearest one.

3.4 THE SYSTEM SHALL show distances rounded to the nearest 50 m (minimum 50 m), and SHALL show
"next door" for any site under 60 m.

3.5 THE SYSTEM SHALL show the construction card for any matched Boston address, rental or not,
because it is about nearby sites and not the building's own history.

## Requirement 4: Construction card by place

**User story:** As a student outside Boston, I want to know what I can check myself, so I'm not
left with nothing.

### Acceptance criteria

4.1 WHEN a Boston address has nearby sites THE SYSTEM SHALL list each with block label, work
label, month issued, and distance, plus an NFPA-based note that a permit means work was
approved, not that it started or finished.

4.2 WHEN a Boston address has no nearby sites THE SYSTEM SHALL say none were found and that
smaller or unpermitted work would not show up.

4.3 WHEN the address is in Amherst (ZIP 01002, 01003, 01004, or 01059, or place Amherst) THE
SYSTEM SHALL explain that Amherst does not publish bulk permit data, suggest asking the landlord,
and link the Town of Amherst permit portal (`https://amherstma.portal.opengov.com`).

4.4 WHEN the address is outside Boston and not in Amherst THE SYSTEM SHALL suggest asking the
landlord or the town building department.

4.5 IF the address is blank, area-only, unmatched in Boston, or the `construction` table is
missing THEN THE SYSTEM SHALL show no construction card.

4.6 THE SYSTEM SHALL show "Data from Analyze Boston: Approved Building Permits" with the
snapshot date and the note that sites are shown by block.

## Requirement 5: Construction question

**User story:** As a student, I want a question to ask the landlord about nearby work.

### Acceptance criteria

5.1 WHEN a Boston address has at least one nearby site THE SYSTEM SHALL add one landlord question
asking how the site is secured and whether the work affects the building's smoke alarms or exits,
saying "next door to" when any site is next door and "near" otherwise.

5.2 THE SYSTEM SHALL cite the question as based on the NFPA construction site fire safety fact
sheet (`nfpa_construction`, not law) and add that source to the report's cited sources.

5.3 IF the context is Amherst, another town, or Boston with no sites THEN THE SYSTEM SHALL add no
construction question.

## Requirement 6: Data Commons build-time fetch

**User story:** As the developer, I want Census figures fetched once at build time, so no
student address ever leaves the app.

### Acceptance criteria

6.1 THE SYSTEM SHALL fetch only at build time, in `scripts/fetch_datacommons.py`, for a fixed
list: every Boston ZIP in `boston.sqlite` (or `sam.csv` before the first build) plus 01002,
01003, 01004, and 01059.

6.2 THE SYSTEM SHALL request the variables `Count_HousingUnit`,
`Count_HousingUnit_Before1939DateBuilt`, `Count_HousingUnit_RenterOccupied`, and
`Count_HousingUnit_OwnerOccupied`, preferring the Census ACS 5-year facet.

6.3 THE SYSTEM SHALL accept the key from `DATACOMMONS_API_KEY` or `DATA_COMMONS_API_KEY`, send it
only in the `X-API-Key` header, and never print or write it, including in error messages.

6.4 IF no key is set, or the key is blank, THEN THE SYSTEM SHALL print a message, make no
request, and exit 0.

6.5 IF a request fails THEN THE SYSTEM SHALL exit 1 with only the HTTP status or error type, and
`scripts/build_data.sh` SHALL continue the build without area housing data.

6.6 WHEN the Docker build provides `DATACOMMONS_API_KEY_FILE` THE SYSTEM SHALL set the key only
for the fetch command.

6.7 THE SYSTEM SHALL write `data/raw/datacommons.json` atomically with source, provenance, dates,
and fetch date, and `preprocess_boston` SHALL load it into a `census_zip` table keyed by ZIP.

## Requirement 7: Census card

**User story:** As a student, I want rough housing facts about the area, so I know which
questions about building age to ask.

### Acceptance criteria

7.1 WHEN the report has a ZIP (the matched Boston ZIP, a ZIP-level area, or a ZIP typed in the
address) and `census_zip` has that ZIP THE SYSTEM SHALL show the share of homes built in 1939 or
earlier and the share of occupied homes that are rented, as whole percents.

7.2 THE SYSTEM SHALL say the figures are about the ZIP code, not this building.

7.3 THE SYSTEM SHALL note that smoke alarm requirements depend on when a building was built or
last renovated, citing Massachusetts smoke alarm rules.

7.4 THE SYSTEM SHALL show "American Community Survey 5-year estimates ending in {year}" and link
the ZIP's Data Commons page.

7.5 IF the address is blank, the ZIP has no row, both figures are missing, or the table is
missing THEN THE SYSTEM SHALL show no census card.

## Requirement 8: No runtime third-party queries and no ranking use

**User story:** As a tenant or student, I want my address kept inside the app, and as a town
inspector I want rankings based only on reports and records.

### Acceptance criteria

8.1 THE SYSTEM SHALL NOT call Data Commons at runtime; the app reads only `census_zip`.

8.2 THE SYSTEM SHALL NOT use Boston's OpenContext MCP at runtime, because it lets an AI query raw
datasets live and would bypass the column whitelists in privacy rule 1.

8.3 THE SYSTEM SHALL NOT use nearby construction or Census figures as ranking inputs.

8.4 WHEN either card is rendered THE SYSTEM SHALL give it a labeled section heading, mark
external links "(opens in a new tab)" for screen readers, and use no em dashes or exclamation
points.
