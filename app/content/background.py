"""Background facts on the About page, each with the public sources that support it.

The About page may cite sources outside the fixed report sources (see the "About page exception"
in .kiro/steering/project-rules.md). Every number here must be supported, as worded, by at least
one linked source. If a number can't be sourced, reword the fact instead of showing it.

Checked October 2026. mass.gov pages block automated fetching, so mass.gov facts were confirmed
from the page text shown in search results.

Founder's original wording, and what changed to match the sources:
- "In Massachusetts in 2024, only 35% of fatal home fires had working smoke alarms, and none of
  those homes had sprinklers." The 35% is 2024 (DFS, March 2025). No 2024 sprinkler figure was
  found; DFS's 2023 summary says none of the residential fire deaths were in sprinklered
  buildings, so the sprinkler part now says 2023.
- "Amherst only began real rental inspections in July 2025, after years of landlords certifying
  their own properties." No source for a July 2025 start was found. Sources confirm the April
  2024 vote requiring inspections every five years, replacing self-certification.
- "The town has about 1,300 rental properties and does around 120 inspections a quarter." 1,258
  properties and 5,134 units are sourced (Gazette, December 2023). No source for 120 inspections
  a quarter was found, so that number was removed.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Citation:
    name: str
    url: str


@dataclass(frozen=True)
class BackgroundFact:
    fact: str
    sources: tuple[Citation, ...]


USFA_CAMPUS = Citation(
    "U.S. Fire Administration, Campus Fire Fatalities in Residential Buildings (2000-2015)",
    "https://www.usfa.fema.gov/downloads/pdf/publications/campus_fire_fatalities_report.pdf",
)
DFS_ALARMS_2025 = Citation(
    "Massachusetts Department of Fire Services, March 2025 smoke and CO alarm release",
    "https://www.mass.gov/news/smoke-co-alarm-reminder-when-you-change-your-clocks-check-your-alarms",
)
DFS_MFIRS_2023 = Citation(
    "Massachusetts Department of Fire Services, 2023 fire data executive summary",
    "https://www.mass.gov/doc/2023-mfirs-executive-summary/download",
)
GAZETTE_SELF_CERT = Citation(
    "Daily Hampshire Gazette, December 2023",
    "https://www.gazettenet.com/Amherst-Town-Council-to-decide-rental-registration-changes-in-new-year-53277596",
)
GAZETTE_RENTAL_COUNT = Citation(
    "Daily Hampshire Gazette, December 2023",
    "https://gazettenet.com/Amherst-Landlords-Association-has-concerns-with-proposed-updates-to-rental-registration-rules-53207802",
)
GAZETTE_INSPECTIONS_2024 = Citation(
    "Daily Hampshire Gazette, April 2024",
    "https://gazettenet.com/New-rental-registration-program-requiring-inspections-to-launch-in-Amherst-54687217",
)
INDY_BYLAW_2024 = Citation(
    "Amherst Indy, April 2024",
    "https://www.amherstindy.org/2024/04/10/town-council-approves-new-rental-registration-bylaw/",
)
UMASS_OLYMPIA = Citation(
    "UMass Amherst, November 2025",
    "https://www.umass.edu/diversity/news/umass-amherst-community-rallies-support-students-affected-olympia-drive-fire",
)
WBUR_OLYMPIA = Citation(
    "WBUR, November 2025",
    "https://www.wbur.org/news/2025/11/12/umass-amherst-apartment-fire-aftermath",
)
UMASS_OFF_CAMPUS_TIMING = Citation(
    "UMass Off-Campus Student Life, resources",
    "https://www.umass.edu/dean-students/off-campus-life/resources",
)
COLLEGIAN_SHORTAGE = Citation(
    "Massachusetts Daily Collegian, February 2024",
    "https://dailycollegian.com/2024/02/umass-role-in-the-amherst-housing-crisis/",
)

BACKGROUND: tuple[BackgroundFact, ...] = (
    BackgroundFact(
        # USFA: 94% of fatal campus-related fires (2000-2015) were in off-campus housing.
        "From 2000 to 2015, 94% of fatal campus-related fires in the U.S. happened in "
        "off-campus housing.",
        (USFA_CAMPUS,),
    ),
    BackgroundFact(
        # DFS March 2025: smoke alarms present and working at about 35% of 2024 fatal fire scenes.
        # DFS 2023 summary: none of the 32 residential fire deaths were in sprinklered buildings.
        "In Massachusetts in 2024, working smoke alarms were confirmed at only about 35% of fatal "
        "fire scenes. In 2023, none of the 32 people who died in residential fires were in "
        "sprinklered buildings.",
        (DFS_ALARMS_2025, DFS_MFIRS_2023),
    ),
    BackgroundFact(
        # UMass: the fire started at a construction site next to the complex; 230 students lost
        # their homes. WBUR: 232 people displaced, 230 of them UMass students.
        "The Olympia Place fire in November 2025 started at a construction site next door and "
        "left about 230 UMass students without a home.",
        (UMASS_OLYMPIA, WBUR_OLYMPIA),
    ),
    BackgroundFact(
        # Gazette Dec 2023: inspections only after complaints, owners self-certify.
        # Gazette and Indy April 2024: council approved inspections of every rental every 5 years.
        "Until 2024, Amherst landlords certified their own rentals, and the town inspected only "
        "after complaints. In April 2024 the town voted to inspect every rental once every five "
        "years.",
        (GAZETTE_SELF_CERT, GAZETTE_INSPECTIONS_2024, INDY_BYLAW_2024),
    ),
    BackgroundFact(
        # Gazette Dec 2023: 1,258 rental properties containing 5,134 units.
        "As of late 2023, the town had nearly 1,300 rental properties with more than 5,000 units.",
        (GAZETTE_RENTAL_COUNT,),
    ),
    BackgroundFact(
        # Collegian Feb 2024: on-campus housing shortage drives up demand and prices off campus.
        # UMass Off-Campus Student Life: aim to sign a lease for the next school year by the end
        # of March or early April.
        "Housing near UMass is in short supply, and UMass advises students to sign a lease for "
        "the next school year by the end of March or early April, months before move-in.",
        (COLLEGIAN_SHORTAGE, UMASS_OFF_CAMPUS_TIMING),
    ),
)
