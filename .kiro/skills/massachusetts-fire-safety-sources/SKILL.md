---
name: massachusetts-fire-safety-sources
description: The seven fixed fire-safety sources TwoWaysOut may cite, and the rules for citing them (by name only, "Required by" only for the three state rules, never implying a unit is safe). Use when writing or reviewing report questions, checklist copy, AI analyzer prompts, building questions, About page text, or anything that cites smoke alarm, carbon monoxide, sanitary code, two-ways-out, heating, electrical, sprinkler, or nearby construction guidance.
metadata:
  project: TwoWaysOut
  source-of-truth: app/content/sources.py
  verified: October 2026
---

# Massachusetts fire-safety sources

TwoWaysOut reports cite exactly seven sources. The source of truth is `app/content/sources.py`; this skill
explains how to use it. If this file and `sources.py` disagree, `sources.py` wins, and this file
should be updated.

## The seven sources

| id | Display name | Cite as | Kind | Allowed relations |
|---|---|---|---|---|
| `sanitary_code` | Massachusetts State Sanitary Code | the Massachusetts State Sanitary Code | law | required_by, recommended_by, based_on |
| `co_alarm_rules` | Massachusetts carbon monoxide alarm rules | Massachusetts carbon monoxide alarm rules | law | required_by, recommended_by, based_on |
| `smoke_alarm_rules` | Massachusetts smoke alarm rules | Massachusetts smoke alarm rules | law | required_by, recommended_by, based_on |
| `umass_off_campus` | UMass Off-Campus Student Life | UMass Off-Campus Student Life | guidance | recommended_by, based_on |
| `amherst_fire` | Amherst Fire Department (Rental Property Overcrowding guidance) | the Amherst Fire Department | guidance | recommended_by, based_on |
| `dfs_college` | Massachusetts Department of Fire Services college fire safety | the Massachusetts Department of Fire Services | guidance | recommended_by, based_on |
| `nfpa_construction` | NFPA construction site fire safety fact sheet | the National Fire Protection Association | guidance | recommended_by, based_on |

Relation text (`app/services/report_models.py`): `required_by` → "Required by",
`recommended_by` → "Recommended by", `based_on` → "Based on guidance from".
`ReportQuestion` rejects `required_by` on a guidance source, so a bad citation fails validation.

## What each source covers

- **State Sanitary Code:** owners provide and maintain smoke and CO alarms, keep exits
  unobstructed, provide enough exits, heat every habitable room from September 15 through May 31,
  and keep electrical and heating equipment maintained to code.
- **CO alarm rules:** CO alarms on every level of each unit (finished basements included) when the
  building has fossil-fuel equipment (gas or oil heat, gas stove) or enclosed parking.
- **Smoke alarm rules:** every home needs working smoke alarms. Exact requirements depend on when
  the building was built or last renovated. Alarms older than 10 years must be replaced.
- **UMass Off-Campus Student Life:** five common factors in off-campus fires (no sprinklers,
  missing or disabled smoke alarms, careless smoking, alcohol, upholstered porch furniture). Always
  have two ways out. Ask the landlord to move a smoke detector rather than disconnecting it.
- **Amherst Fire Department:** attic, basement, or closet bedrooms often have one way out and no
  smoke detector. Covered detectors delay warnings. Too few outlets lead to extension cords and
  electrical fires. Always have two ways out.
- **DFS college fire safety:** students need working smoke and CO alarms and two ways out.
  Windows, doors, and stairways should be kept clear.
- **NFPA construction fact sheet:** buildings under construction may not yet have working
  sprinklers, smoke detection, or alarms; sites have many ignition sources (heaters, hot work);
  lapses can damage adjacent buildings. Used only for the nearby-construction question.

## Which source to use

| Topic | Requirement (law) | Guidance |
|---|---|---|
| Smoke alarms | `smoke_alarm_rules`, `sanitary_code` | `umass_off_campus`, `amherst_fire` |
| CO alarms | `co_alarm_rules` | `dfs_college` |
| Two ways out / blocked exits | `sanitary_code` | `dfs_college`, `umass_off_campus`, `amherst_fire` |
| Bedrooms in basement/attic/den | `sanitary_code` (exits) | `amherst_fire` |
| Heating / space heaters | `sanitary_code` | none |
| Electrical / extension cords | `sanitary_code` (maintenance) | `amherst_fire` |
| Sprinklers | none (don't claim a requirement) | `umass_off_campus` |
| Construction next door | none | `nfpa_construction` |

## Nearest-college guidance

TwoWaysOut isn't only for UMass students. College guidance comes from `app/content/colleges.py`:
UMass Amherst (`umass_off_campus`), Boston University (`bu_off_campus`), Tufts
(`tufts_off_campus`), and MIT (`mit_off_campus`), each from its official off-campus fire safety
page. `app/services/colleges.py` picks the college nearest the rental (or the one the student
chose) and re-points college citations to it, only for topics that college's `topics` covers.
Otherwise it uses `nfpa_campus` (NFPA college campus tips) or the State Sanitary Code. Amherst
Fire Department citations stay only for Amherst rentals. To add a college, fetch and read its
official off-campus fire safety page first, then add a `Source` and a `College` entry.

## Rules

1. Cite only these seven, by name. Never cite section numbers (no "105 CMR 410.xxx", "527 CMR 31",
   "§", "Section 4"). Regulation numbers may appear only inside a source URL.
2. Only the three law sources may be "Required by". Everything else is "Recommended by" or
   "Based on guidance from".
3. Never say or imply a unit is safe, compliant, or up to code. Frame findings as questions to ask
   the landlord.
4. Every student report shows, verbatim: "This is general information, not legal advice. Contact
   your local Board of Health to request an inspection."
5. Don't paraphrase a source beyond what its summary in `sources.py` supports. If you need a new
   claim, check the source page first and update the summary.
6. The AI analyzer only gets source IDs from `SOURCE_IDS` (JSON schema enum). Don't add free-text
   citation fields.

About page exception (approved by the owner): the founder-story background in
`app/content/background.py` may cite news, government reports, and research outside this list.
Every number there needs a linked source that supports it as worded. If a number can't be
sourced, reword the fact rather than show it.

Data sources (Analyze Boston datasets, Data Commons / U.S. Census, the Amherst permit portal) are
shown as "Data from", never as rules, and never as "Required by".

## Changing the source list

Only the project owner can add, remove, or replace a source. If asked to:

1. Update `SourceId`, `SOURCES`, and the summary in `app/content/sources.py`. Set `is_law` correctly.
2. Update the source list in `.kiro/steering/project-rules.md` and in this skill.
3. Update any `source_id=` uses in `app/content/questions.py`, `app/content/checklist.py`,
   `app/services/building_questions.py`, and `app/services/rules_analyzer.py`.
4. Run `.venv/bin/pytest -q`.

## Verification notes

- mass.gov pages return HTTP 403 to automated fetching. Their URLs come from search results and
  should be checked by hand in a browser.
- The UMass and Amherst pages were fetched and read in October 2026.
- `amherstfd.org` is Amherst, **Wisconsin**. Never use it. The Amherst, MA guidance is the
  "Rental Property Overcrowding" page on amherstma.gov.

## Checking content

Run the checker on changed files (or with no arguments to scan `app/content/`, `app/templates/`,
and the analyzers):

```bash
.venv/bin/python .kiro/skills/massachusetts-fire-safety-sources/scripts/check_citations.py [files...]
```

It flags section-number citations, em dashes in UI copy, safe/compliant claims, and `required_by`
on guidance sources. It exits 1 when it finds something. It doesn't catch citations of sources
outside the seven by name; review those by hand.
