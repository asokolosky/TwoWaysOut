"""Pick the college nearest a rental, and localize student-guidance citations to it.

Boston addresses matched to the city's address list have coordinates, so the nearest campus is
picked by distance. Other addresses are matched by ZIP code, then by town name. The student can
also pick their college on the form. Nothing is sent anywhere; this is all local data.

Questions and checklist text that cite a college's guidance are re-pointed to the chosen
college when its page covers that topic, and to the NFPA campus tips otherwise. So a student in
Cambridge never gets UMass Amherst advice.
"""

import math

from app.content.checklist import TOPICS, TopicInfo
from app.content.colleges import (
    COLLEGE_SOURCE_IDS,
    COLLEGES,
    COLLEGES_BY_ID,
    GENERAL_STUDENT_SOURCE,
    GENERAL_TOPICS,
    College,
)
from app.services.address_normalize import parse_address
from app.services.report_models import LandlordQuestion, SafetyReport

MAX_DISTANCE_KM = 5.0
# Topics whose checklist "why" text comes from student guidance rather than state rules.
STUDENT_GUIDANCE_TOPICS = frozenset(t for t, info in TOPICS.items() if info.source_id in COLLEGE_SOURCE_IDS)


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(a))


def nearest_college(
    address: str, lat: float | None = None, lon: float | None = None, chosen: str | None = None
) -> College | None:
    """The student's chosen college, else the nearest one we have verified guidance for."""
    if chosen and chosen in COLLEGES_BY_ID:
        return COLLEGES_BY_ID[chosen]
    if lat is not None and lon is not None:
        best = min(COLLEGES, key=lambda c: _km(lat, lon, c.lat, c.lon))
        if _km(lat, lon, best.lat, best.lon) <= MAX_DISTANCE_KM:
            return best
    parsed = parse_address(address or "")
    if parsed is None:
        return None
    if parsed.zip:
        for c in COLLEGES:
            if parsed.zip in c.zips:
                return c
    place = set((parsed.place or "").upper().replace(",", " ").split())
    for c in COLLEGES:
        if place & c.towns:
            return c
    return None


def _source_for(topic: str, college: College | None) -> str:
    if college is not None and topic in college.topics:
        return college.source_id
    return GENERAL_STUDENT_SOURCE


def _local_fallback(topic: str, college: College | None) -> str:
    """For town-specific guidance (Amherst FD) used outside that town."""
    if college is not None and topic in college.topics:
        return college.source_id
    if topic in GENERAL_TOPICS:
        return GENERAL_STUDENT_SOURCE
    return "sanitary_code"  # covers electrical and heating maintenance statewide


def localize_report(report: SafetyReport, college: College | None, in_amherst: bool = False) -> SafetyReport:
    """Re-point college and town guidance to the rental's area.

    College citations go to the chosen college when its page covers the topic, else the NFPA
    campus tips. Amherst Fire Department citations stay only for Amherst rentals.
    """
    questions: list[LandlordQuestion] = []
    for q in report.questions:
        new = q.source_id
        if q.source_id in COLLEGE_SOURCE_IDS or q.source_id == GENERAL_STUDENT_SOURCE:
            new = _source_for(q.topic, college)
        elif q.source_id == AMHERST_FIRE and not in_amherst:
            new = _local_fallback(q.topic, college)
        if new != q.source_id:
            q = q.model_copy(update={"source_id": new, "relation": "based_on"})
        if q.question not in {x.question for x in questions}:
            questions.append(q)
    return report.model_copy(update={"questions": questions})


def localized_topics(college: College | None, in_amherst: bool = False) -> dict[str, TopicInfo]:
    """Checklist topics, with student and town guidance taken from the rental's area."""
    out = dict(TOPICS)
    for topic, info in TOPICS.items():
        if info.source_id in COLLEGE_SOURCE_IDS or (info.source_id == AMHERST_FIRE and not in_amherst):
            if college is not None and topic in college.topics:
                out[topic] = TopicInfo(label=info.label, why=college.topics[topic], source_id=college.source_id)
            elif topic in GENERAL_TOPICS:
                out[topic] = TopicInfo(label=info.label, why=GENERAL_TOPICS[topic], source_id=GENERAL_STUDENT_SOURCE)
            elif topic in STATE_TOPICS:
                out[topic] = TopicInfo(label=info.label, why=STATE_TOPICS[topic], source_id="sanitary_code")
    return out


AMHERST_FIRE = "amherst_fire"
# Statewide fallback text, supported by the State Sanitary Code summary in sources.py.
STATE_TOPICS = {
    "electrical": "The Massachusetts State Sanitary Code requires owners to keep electrical "
    "equipment installed and maintained properly.",
}
