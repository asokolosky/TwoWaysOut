# Design: Nearby construction and area housing (Census) cards

## Overview

Both cards are built from tables in the read-only `data/boston.sqlite`. All outside data is
fetched and reduced at build time, so a student's address is only ever compared against local
tables. `_area_context` in `app/routers/check.py` builds both contexts for every check, and
`_report_context` adds the construction question and its NFPA source to the report.

## Data flow

```
scripts/build_data.sh
  1. scripts.fetch_boston               -> data/raw/permits.csv (and the other Boston datasets)
  2. scripts.fetch_datacommons          -> data/raw/datacommons.json   (only when a key is set;
                                           failure prints a message and the build continues)
  3. scripts.preprocess_boston
       permits read with usecols = history.PERMIT_COLUMNS | construction.CONSTRUCTION_COLUMNS
       construction.build_construction()  -> construction table + idx_construction_latlon
       load_census(datacommons.json)      -> census_zip table + unique idx_census_zip

POST /check -> _area_context(address, boston, boston_db)
  construction_context() -> ConstructionContext(kind=boston|amherst|other) or None
  census_context()       -> CensusContext or None
  construction_questions(construction) -> 0 or 1 LandlordQuestion (nfpa_construction)
  partials/report.html   -> construction_card.html, census_card.html
```

## Components

- `scripts/construction.py`: `classify()` applies the rules in Requirement 1. `block_label()`
  turns an address into "N block of Street" or refuses (`None`). `build_construction()` filters
  to the 24-month window, classifies, resolves the parcel (parcel ID, else property ID through
  SAM, then to the building parcel), drops rows without a label or with coordinates outside
  Boston, rounds coordinates to 4 decimals, and keeps one row per site.
- `app/services/construction.py`: `nearby_construction()` runs a bounding-box query (250 m
  converted to degrees, with a cosine correction for longitude), then filters by haversine
  distance, drops the own parcel and parcel-less points within 10 m, sorts nearest first,
  dedupes by (block label, work label), and returns up to 8 sites with rounded distances.
  `construction_context()` picks Boston, Amherst, or other.
- `app/services/building_questions.py`: `construction_questions()` returns the single NFPA-based
  question for Boston contexts with sites.
- `scripts/fetch_datacommons.py`: posts to `https://api.datacommons.org/v2/observation` in batches
  of 50 ZIPs, with the key in `X-API-Key`. `_pick_facet` prefers `CensusACS5YearSurvey`.
- `app/services/census.py`: `zip_for_report()` picks the ZIP, `census_for_zip()` reads one row
  and computes whole percents. The renter share uses renter plus owner occupied as the base.
- Templates: `construction_card.html` and `census_card.html`, each a `section` with
  `aria-labelledby` pointing at its `h3`.

## Data model

`construction` (no valuation, permit number, applicant, comments, or house number):

| Column | Notes |
| --- | --- |
| `parcel_id` | Building parcel, used only to exclude the matched building; may be NULL |
| `lat`, `lon` | Rounded to 4 decimals |
| `block_label` | "1-99 block of Boardman St" |
| `kind` | `new_construction` or `major_work` |
| `work_label` | e.g. "New building", "Demolition" |
| `issued_month` | `YYYY-MM` |
| `status` | Permit status |

`census_zip`: `zip`, `housing_units`, `built_before_1940`, `renter_occupied`, `owner_occupied`,
`year` (latest observation date), `fetched`.

## Block labels and the privacy review

The house number is reduced to its hundred ("182" becomes "100 block", "31" becomes "1-99
block"). A privacy review found inputs where the old cleanup kept part of the address, such as
"12 1/2 Main ST", "12 14 Main ST", "12 & 14 Main ST", "1200 Rear 14 Main ST", "12 A Main ST",
"12 Main ST Unit B", and "12 Main ST 2nd FL". The fix is to refuse rather than clean up: any
fraction or `#`, second number, joiner word, unit word, non-ordinal number in the street part,
or single-letter unit before a multi-word street returns `None`, and that site is not shown.
Ordinal streets ("5th St") and single-letter street names ("B St") are still allowed. Losing a
few odd addresses is the accepted cost.

## Distance and precision

Stored coordinates are rounded to about 11 m, which is enough to tell "next door" (under 60 m)
and 50 m bands apart but not enough to pinpoint a house. Shown distances are rounded to 50 m,
with a 50 m minimum.

## Why no runtime outside queries

- Data Commons is called only by the build script for a fixed ZIP list. At runtime the app reads
  `census_zip`, so no student or tenant address is sent anywhere (privacy rule 7).
- Boston's OpenContext MCP is not used by the app. It lets an AI query raw datasets live, which
  would bypass the `usecols` whitelists in privacy rule 1 and the block-level rule 8.
- Neither table is read by `app/services/ranking.py`.

## Results from the rebuilt database

Snapshot 2026-10-24:

- `construction` has 1,551 sites, and 0 block labels have digits in the street part.
- Data Commons returned 38 of 40 ZIPs, ACS 5-year estimates ending in 2024.
- 01002 (Amherst): 23% of homes built 1939 or earlier, 53% of occupied homes rented.
- 02120 (Boston, Mission Hill): 28% built 1939 or earlier, 91% rented.

## Testing

- `tests/test_construction.py`: classification, table contents, no PII or exact address,
  whitelist, no stored valuation, distance helpers, own-parcel exclusion, context by place,
  question wording, card rendering and copy rules.
- `tests/test_round2_block_label.py`: edge cases, refusals where a number could leak, the
  privacy-review cases, and a check that no label contains the house number.
- `tests/test_census.py`: verified dcids, place list, no-key exit, JSON output, key not leaked,
  build script key handling, loader, ZIP choice, card rendering, no ranking use, no runtime calls.
- `tests/test_round2_datacommons.py`: key stays in the header across batches and never appears
  in output on HTTP, network, or JSON errors; a blank key makes no request.
- `tests/test_round2_check_cards.py`: end-to-end cards on `/check` for Boston, Amherst, other
  towns, and blank addresses, plus heading order and copy rules.
