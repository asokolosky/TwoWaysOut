"""The fixed list of sources TwoWaysOut may cite. Nothing outside this list is ever cited.

Display text cites sources by name only, never by section number.

Verification notes (October 2026):
- mass.gov pages block automated fetching (HTTP 403), so their URLs come from search results
  and could not be opened directly.
- The UMass and Amherst pages were fetched and read.
- The Amherst Fire Department does not appear to publish a standalone off-campus checklist.
  Its "Rental Property Overcrowding" page covers off-campus fire safety and is used instead.
  (The amherstfd.org checklist found in search belongs to Amherst, Wisconsin.)
- The NFPA construction site fact sheet PDF was downloaded and read. Its summary below follows
  the "Risk Factors" and "Key Issues" sections. It is guidance, cited only for construction
  near a building ("based_on" or "recommended_by").
"""

from dataclasses import dataclass
from typing import Literal, get_args

SourceId = Literal[
    "sanitary_code",
    "co_alarm_rules",
    "smoke_alarm_rules",
    "umass_off_campus",
    "amherst_fire",
    "dfs_college",
    "nfpa_construction",
    "bu_off_campus",
    "tufts_off_campus",
    "mit_off_campus",
    "nfpa_campus",
]


@dataclass(frozen=True)
class Source:
    id: str
    name: str  # shown in the sources list
    cite_as: str  # used inside a citation, e.g. "Required by {cite_as}"
    url: str
    is_law: bool  # only law/regulation sources may be cited as "Required by"
    summary: str  # what the source covers; also given to the AI analyzer in Task 3


SOURCES: dict[str, Source] = {
    s.id: s
    for s in [
        Source(
            id="sanitary_code",
            name="Massachusetts State Sanitary Code",
            cite_as="the Massachusetts State Sanitary Code",
            url="https://www.mass.gov/regulations/105-CMR-41000-minimum-standards-of-fitness-for-human-habitation-state-sanitary-code-chapter-ii",
            is_law=True,
            summary=(
                "Minimum housing standards for Massachusetts rentals. Owners must provide and "
                "maintain smoke detectors and carbon monoxide alarms, keep exits unobstructed, "
                "provide enough exits for safe passage, provide heat in every habitable room "
                "from September 15 through May 31, and keep electrical and heating equipment "
                "installed and maintained to code."
            ),
        ),
        Source(
            id="co_alarm_rules",
            name="Massachusetts carbon monoxide alarm rules",
            cite_as="Massachusetts carbon monoxide alarm rules",
            url="https://www.mass.gov/info-details/massachusetts-law-about-carbon-monoxide-detectors",
            is_law=True,
            summary=(
                "Carbon monoxide alarms are required in residential buildings that have "
                "fossil-fuel burning equipment (such as gas or oil heat or a gas stove) or "
                "enclosed parking, on every level of each unit including finished basements."
            ),
        ),
        Source(
            id="smoke_alarm_rules",
            name="Massachusetts smoke alarm rules",
            cite_as="Massachusetts smoke alarm rules",
            url="https://www.mass.gov/doc/firefactors-smoke-alarm-requirements-1112016/download",
            is_law=True,
            summary=(
                "Every Massachusetts home must have working smoke alarms. The exact "
                "requirements depend on when the building was built or last renovated. "
                "Alarms older than 10 years must be replaced."
            ),
        ),
        Source(
            id="umass_off_campus",
            name="UMass Off-Campus Student Life",
            cite_as="UMass Off-Campus Student Life",
            url="https://www.umass.edu/dean-students/off-campus-life/safety",
            is_law=False,
            summary=(
                "Lists five common factors in off-campus housing fires: no automatic "
                "sprinklers, missing or disabled smoke alarms, careless smoking, alcohol, and "
                "upholstered furniture on porches. Advises always having two ways out and "
                "asking the landlord to move a smoke detector rather than disconnecting it."
            ),
        ),
        Source(
            id="amherst_fire",
            name="Amherst Fire Department (Rental Property Overcrowding guidance)",
            cite_as="the Amherst Fire Department",
            url="https://www.amherstma.gov/3556/Rental-Property-Overcrowding",
            is_law=False,
            summary=(
                "Warns that bedrooms in attics, basements, or closets often have only one way "
                "out and no smoke detectors, that covered or removed smoke detectors delay "
                "warnings, and that too few outlets lead to extension cords, overloaded "
                "circuits, and electrical fires. Advises always having two ways out."
            ),
        ),
        Source(
            id="dfs_college",
            name="Massachusetts Department of Fire Services college fire safety",
            cite_as="the Massachusetts Department of Fire Services",
            url="https://www.mass.gov/info-details/college-fire-safety",
            is_law=False,
            summary=(
                "Students need working smoke and carbon monoxide alarms and two ways out of "
                "any place they live. Windows, doors, and stairways should be kept clear."
            ),
        ),
        Source(
            id="nfpa_construction",
            name="NFPA construction site fire safety fact sheet",
            cite_as="the National Fire Protection Association",
            url="https://www.nfpa.org/-/media/Project/Storefront/Catalog/Files/Code-or-topic-fact-sheets/ConstructionSafetyFactSheet.pdf",
            is_law=False,
            summary=(
                "Buildings under construction may not yet have working sprinklers, smoke "
                "detection, or fire alarms. Construction sites are often unsecured and have many "
                "ignition sources, such as heaters and hot work like welding, cutting, and "
                "roofing. A lapse in safety procedures can damage adjacent buildings. Sites "
                "should be safeguarded around the clock, not just when work is being done."
            ),
        ),
        # College off-campus fire safety pages (checked October 2026). The report uses the one
        # for the college nearest the rental (app/content/colleges.py).
        Source(
            id="bu_off_campus",
            name="Boston University fire safety tips for students on and off campus",
            cite_as="Boston University",
            url="https://www.bu.edu/articles/2017/fire-safety-tips/",
            is_law=False,
            summary=(
                "Before moving in, check for working smoke and carbon monoxide detectors, with a "
                "smoke detector outside each sleeping area and a CO detector on each level. Know "
                "two escape routes and keep them clear, and check for locks that would block "
                "getting out. Don't overload outlets, and never heat with a gas stove or oven."
            ),
        ),
        Source(
            id="tufts_off_campus",
            name="Tufts University Off Campus Housing Fire Safety",
            cite_as="the Tufts University Fire Safety Office",
            url="https://publicsafety.tufts.edu/fire-safety/protocols-guides/campus-housing",
            is_law=False,
            summary=(
                "Lists factors in off-campus student housing fires: no fire sprinklers, missing "
                "or disabled smoke and carbon monoxide detection, smoking materials, unattended "
                "cooking, more occupants, and alcohol. Advises weighing a building's fire "
                "protection features when choosing a rental."
            ),
        ),
        Source(
            id="mit_off_campus",
            name="MIT Off-Campus Housing: Off-Campus Safety and Security",
            cite_as="MIT Off-Campus Housing",
            url="https://mit.helpscoutdocs.com/article/2285-off-campus-safety-securit",
            is_law=False,
            summary=(
                "Check that the unit has a working smoke detector. If the landlord won't install "
                "or repair smoke or carbon monoxide detectors, report it to the fire department."
            ),
        ),
        Source(
            id="nfpa_campus",
            name="NFPA college campus fire safety tips",
            cite_as="the National Fire Protection Association",
            url="https://content.nfpa.org/-/media/project/storefront/catalog/files/safety-tip-sheets/campussafetytips.pdf",
            is_law=False,
            summary=(
                "Look for fully sprinklered housing when choosing a dorm or off-campus housing. "
                "Off campus, have a fire escape plan with two ways out of every room. Test smoke "
                "alarms monthly; interconnected alarms give the best protection."
            ),
        ),
    ]
}

SOURCE_IDS: tuple[str, ...] = get_args(SourceId)
LEGAL_SOURCE_IDS = frozenset(s.id for s in SOURCES.values() if s.is_law)
