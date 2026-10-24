"""Colleges whose own off-campus fire safety guidance the report can use.

Each college here has an official off-campus fire safety page that was fetched and read
(October 2026); its citation is a Source in app/content/sources.py. Colleges without a page that
could be verified are left out, and reports near them use statewide and national guidance.

`topics` holds one plain sentence per checklist topic the page actually covers. Nothing here
is a ranking input.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class College:
    id: str
    name: str
    short_name: str
    source_id: str
    lat: float
    lon: float
    towns: frozenset[str]  # uppercase town or neighborhood names
    zips: frozenset[str]
    topics: dict[str, str] = field(default_factory=dict)


COLLEGES: tuple[College, ...] = (
    College(
        id="umass_amherst",
        name="University of Massachusetts Amherst",
        short_name="UMass Amherst",
        source_id="umass_off_campus",
        lat=42.3868,
        lon=-72.5301,
        towns=frozenset({"AMHERST", "HADLEY", "SUNDERLAND"}),
        zips=frozenset({"01002", "01003", "01004", "01059", "01035", "01375"}),
        topics={
            "smoke_alarms": "UMass lists missing or disabled smoke alarms as a common factor in "
            "off-campus fires, and advises asking the landlord to move a detector rather than "
            "disconnecting it.",
            "two_ways_out": "UMass advises always having two ways out.",
            "sprinklers": "UMass lists missing sprinklers as a common factor in off-campus "
            "housing fires.",
        },
    ),
    College(
        id="bu",
        name="Boston University",
        short_name="BU",
        source_id="bu_off_campus",
        lat=42.3505,
        lon=-71.1054,
        towns=frozenset({"BROOKLINE", "ALLSTON", "BRIGHTON", "FENWAY"}),
        zips=frozenset({"02215", "02134", "02135", "02446"}),
        topics={
            "smoke_alarms": "BU advises checking for working smoke and carbon monoxide detectors "
            "before moving in, with a smoke detector outside each sleeping area and a CO "
            "detector on each level.",
            "two_ways_out": "BU advises knowing two escape routes, keeping them clear, and "
            "checking for locks that would keep you from getting out.",
            "heating": "BU warns never to heat an apartment with a gas stove or oven.",
            "electrical": "BU advises not overloading outlets and using UL-listed cords and "
            "power strips.",
        },
    ),
    College(
        id="tufts",
        name="Tufts University",
        short_name="Tufts",
        source_id="tufts_off_campus",
        lat=42.4075,
        lon=-71.1190,
        towns=frozenset({"MEDFORD", "SOMERVILLE"}),
        zips=frozenset({"02155", "02144", "02145", "02143"}),
        topics={
            "smoke_alarms": "Tufts lists missing or disabled smoke and carbon monoxide detection "
            "as a factor in off-campus student housing fires.",
            "sprinklers": "Tufts lists a lack of fire sprinkler protection as a factor in "
            "off-campus student housing fires.",
        },
    ),
    College(
        id="mit",
        name="Massachusetts Institute of Technology",
        short_name="MIT",
        source_id="mit_off_campus",
        lat=42.3601,
        lon=-71.0942,
        towns=frozenset({"CAMBRIDGE"}),
        zips=frozenset({"02139", "02138", "02141", "02142"}),
        topics={
            "smoke_alarms": "MIT advises checking that the unit has a working smoke detector, "
            "and reporting a landlord who won't fix smoke or CO detectors to the fire department.",
        },
    ),
)

COLLEGES_BY_ID = {c.id: c for c in COLLEGES}
COLLEGE_SOURCE_IDS = frozenset(c.source_id for c in COLLEGES)

# Used for a topic when the nearest college's page doesn't cover it, or no college is known.
GENERAL_STUDENT_SOURCE = "nfpa_campus"
GENERAL_TOPICS = {
    "smoke_alarms": "The National Fire Protection Association advises testing smoke alarms "
    "monthly, and says interconnected alarms give the best protection.",
    "two_ways_out": "The National Fire Protection Association advises students off campus to "
    "have a fire escape plan with two ways out of every room.",
    "sprinklers": "The National Fire Protection Association advises looking for fully "
    "sprinklered housing when choosing off-campus housing.",
}
