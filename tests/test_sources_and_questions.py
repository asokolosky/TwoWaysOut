import re

import pytest
from pydantic import ValidationError

from app.content.checklist import TOPICS
from app.content.questions import QUESTION_BANK
from app.content.sources import LEGAL_SOURCE_IDS, SOURCE_IDS, SOURCES
from app.services.report_models import TOPIC_ORDER, LandlordQuestion

SECTION_NUMBER = re.compile(r"\d+\s*CMR|§|\bsection\s+\d", re.IGNORECASE)


def test_exactly_the_allowed_sources():
    assert set(SOURCES) == set(SOURCE_IDS)
    # Seven report sources plus three college pages (BU, Tufts, MIT) and the NFPA campus tips.
    assert len(SOURCES) == 11
    assert LEGAL_SOURCE_IDS == {"sanitary_code", "co_alarm_rules", "smoke_alarm_rules"}


def test_nfpa_construction_source():
    s = SOURCES["nfpa_construction"]
    assert s.name == "NFPA construction site fire safety fact sheet"
    assert s.cite_as == "the National Fire Protection Association"
    assert s.url == (
        "https://www.nfpa.org/-/media/Project/Storefront/Catalog/Files/"
        "Code-or-topic-fact-sheets/ConstructionSafetyFactSheet.pdf"
    )
    assert s.is_law is False
    for phrase in ("sprinklers", "smoke detection", "fire alarms", "heaters", "adjacent buildings"):
        assert phrase in s.summary
    with pytest.raises(ValidationError):
        LandlordQuestion(topic="two_ways_out", question="?", source_id="nfpa_construction", relation="required_by")
    for relation in ("based_on", "recommended_by"):
        q = LandlordQuestion(topic="two_ways_out", question="?", source_id="nfpa_construction", relation=relation)
        assert q.citation.endswith("the National Fire Protection Association")


def test_source_display_text_has_no_section_numbers():
    for s in SOURCES.values():
        for text in (s.name, s.cite_as, s.summary):
            assert not SECTION_NUMBER.search(text), (s.id, text)
        assert s.url.startswith("https://")


def test_every_topic_has_info_with_valid_source():
    assert set(TOPICS) == set(TOPIC_ORDER)
    for info in TOPICS.values():
        assert info.source_id in SOURCES
        assert not SECTION_NUMBER.search(info.why)


def test_question_bank_cites_only_allowed_sources_by_name():
    for key, q in QUESTION_BANK.items():
        assert q.source_id in SOURCES, key
        assert not SECTION_NUMBER.search(q.question), key
        assert not SECTION_NUMBER.search(q.citation), key
        assert SOURCES[q.source_id].cite_as in q.citation


def test_citation_wording():
    q = QUESTION_BANK["heat_every_room"]
    assert q.citation == "Required by the Massachusetts State Sanitary Code"


def test_unknown_source_rejected():
    with pytest.raises(ValidationError):
        LandlordQuestion(
            topic="heating", question="?", source_id="national_code_of_awesome", relation="based_on"
        )


def test_guidance_cannot_be_cited_as_requirement():
    with pytest.raises(ValidationError):
        LandlordQuestion(
            topic="two_ways_out", question="?", source_id="dfs_college", relation="required_by"
        )
