"""The five checklist items and why each one matters. Every item names one allowed source."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TopicInfo:
    label: str
    why: str
    source_id: str


TOPICS: dict[str, TopicInfo] = {
    "smoke_alarms": TopicInfo(
        label="Working smoke alarms, and carbon monoxide alarms where required",
        why=(
            # Only what the linked smoke alarm rules say. Carbon monoxide alarms depend on
            # fossil-fuel equipment or enclosed parking; that's in the CO question, which
            # cites co_alarm_rules (app/content/questions.py).
            "Massachusetts requires working smoke alarms in every home. The exact requirements "
            "depend on when the building was built or last renovated, and alarms older than "
            "10 years must be replaced."
        ),
        source_id="smoke_alarm_rules",
    ),
    "two_ways_out": TopicInfo(
        label="Two ways out of every bedroom",
        why=(
            "The Massachusetts Department of Fire Services tells students to make sure they "
            "have two ways out of any place they live."
        ),
        source_id="dfs_college",
    ),
    "sprinklers": TopicInfo(
        label="Automatic sprinklers",
        why=(
            "UMass Off-Campus Student Life lists missing sprinklers as a common factor in "
            "off-campus housing fires."
        ),
        source_id="umass_off_campus",
    ),
    "heating": TopicInfo(
        label="Heating that works in every room",
        why=(
            "The Massachusetts State Sanitary Code requires heat in every habitable room from "
            "September 15 through May 31."
        ),
        source_id="sanitary_code",
    ),
    "electrical": TopicInfo(
        label="Electrical system condition",
        why=(
            "The Amherst Fire Department warns that too few outlets leads to extension cords, "
            "overloaded circuits, and electrical fires."
        ),
        source_id="amherst_fire",
    ),
}
