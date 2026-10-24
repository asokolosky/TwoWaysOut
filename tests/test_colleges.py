"""Nearest-college fire safety guidance: picking the college and localizing citations."""

import re

import pytest

from app.content.colleges import COLLEGE_SOURCE_IDS, COLLEGES, GENERAL_STUDENT_SOURCE
from app.content.sources import LEGAL_SOURCE_IDS, SOURCES
from app.services.colleges import localize_report, localized_topics, nearest_college
from app.services.report_models import LandlordQuestion, SafetyReport

LISTING = (
    "Sunny 3BR apartment, second floor of a three-family. Heat included. Third bedroom is off "
    "the kitchen. Coin laundry in the basement. Lease starts September 1."
)


def test_every_college_has_a_guidance_source():
    for c in COLLEGES:
        src = SOURCES[c.source_id]
        assert src.id not in LEGAL_SOURCE_IDS
        assert src.url.startswith("https://")
        assert c.topics, c.id


@pytest.mark.parametrize(
    "address, lat, lon, expected",
    [
        ("12 Example St, Amherst, MA 01002", None, None, "umass_amherst"),
        ("12 Example St, Amherst, MA", None, None, "umass_amherst"),
        ("10 Main St, Cambridge, MA 02139", None, None, "mit"),
        ("10 College Ave, Somerville, MA 02144", None, None, "tufts"),
        ("20 Linden St, Allston", 42.3530, -71.1300, "bu"),  # matched Boston point near BU
        ("10 Main St, Worcester, MA 01609", None, None, None),  # no verified college there
        ("", None, None, None),
    ],
)
def test_nearest_college(address, lat, lon, expected):
    c = nearest_college(address, lat=lat, lon=lon)
    assert (c.id if c else None) == expected


def test_far_boston_point_falls_back_to_zip_or_none():
    # Dorchester point is more than 5 km from every campus, and 02122 isn't a college ZIP.
    assert nearest_college("10 Adams St, Dorchester 02122", lat=42.2950, lon=-71.0600) is None


def test_chosen_college_wins():
    assert nearest_college("12 Example St, Amherst, MA 01002", chosen="mit").id == "mit"
    assert nearest_college("12 Example St, Amherst, MA 01002", chosen="not-a-college").id == "umass_amherst"


def _report(source_id, topic="sprinklers"):
    q = LandlordQuestion(topic=topic, question="Does the building have sprinklers?", source_id=source_id, relation="based_on")
    return SafetyReport(analyzer="rules", checklist=[], flags=[], questions=[q])


def test_umass_citation_moves_to_nearest_college_when_covered():
    tufts = nearest_college("10 College Ave, Somerville, MA 02144")
    out = localize_report(_report("umass_off_campus"), tufts)
    assert out.questions[0].source_id == "tufts_off_campus"


def test_citation_falls_back_to_nfpa_when_college_doesnt_cover_topic():
    mit = nearest_college("10 Main St, Cambridge, MA 02139")
    out = localize_report(_report("umass_off_campus"), mit)  # MIT's page doesn't cover sprinklers
    assert out.questions[0].source_id == GENERAL_STUDENT_SOURCE


def test_no_college_never_cites_umass():
    out = localize_report(_report("umass_off_campus"), None)
    assert out.questions[0].source_id == GENERAL_STUDENT_SOURCE
    topics = localized_topics(None)
    assert all(info.source_id not in COLLEGE_SOURCE_IDS for info in topics.values())


def test_umass_kept_for_amherst():
    umass = nearest_college("12 Example St, Amherst, MA 01002")
    assert localize_report(_report("umass_off_campus"), umass).questions[0].source_id == "umass_off_campus"
    assert localized_topics(umass)["sprinklers"].source_id == "umass_off_campus"


def test_amherst_fire_only_for_amherst_rentals():
    q = _report("amherst_fire", topic="electrical")
    bu = nearest_college("20 Linden St, Allston", lat=42.3530, lon=-71.1300)
    assert localize_report(q, bu).questions[0].source_id == "bu_off_campus"  # BU covers electrical
    assert localize_report(q, None).questions[0].source_id == "sanitary_code"
    assert localize_report(q, None, in_amherst=True).questions[0].source_id == "amherst_fire"
    assert localized_topics(None)["electrical"].source_id == "sanitary_code"
    assert localized_topics(None, in_amherst=True)["electrical"].source_id == "amherst_fire"


def test_cambridge_report_has_no_amherst_or_umass(client):
    html = _post(client, "10 Main St, Cambridge, MA 02139")
    body = re.sub(r"<select.*?</select>", "", html, flags=re.S)
    assert "Amherst Fire Department" not in body and "UMass" not in body


def test_amherst_report_keeps_local_sources(client):
    html = _post(client, "12 Example St, Amherst, MA 01002")
    assert "Amherst Fire Department" in html and "Off-campus fire safety from UMass Amherst" in html


def test_state_rule_citations_untouched():
    out = localize_report(_report("sanitary_code", topic="heating"), None)
    assert out.questions[0].source_id == "sanitary_code"


def _post(client, address, college=""):
    return client.post("/check", data={"listing": LISTING, "address": address, "college": college}).text


def test_report_shows_nearest_college_card(client):
    html = _post(client, "10 Main St, Cambridge, MA 02139")
    assert 'id="college-heading"' in html and "Off-campus fire safety from MIT" in html
    assert SOURCES["mit_off_campus"].url in html
    assert "UMass" not in re.sub(r"<select.*?</select>", "", html, flags=re.S)


def test_report_without_college_has_no_umass_and_no_card(client):
    html = _post(client, "10 Main St, Worcester, MA 01609")
    assert 'id="college-heading"' not in html
    assert "UMass" not in re.sub(r"<select.*?</select>", "", html, flags=re.S)
    assert SOURCES["nfpa_campus"].url in html


def test_chosen_college_on_form(client):
    html = _post(client, "10 Main St, Worcester, MA 01609", college="bu")
    assert "Off-campus fire safety from BU" in html and "You chose Boston University." in html


def test_unknown_college_value_ignored(client):
    html = _post(client, "10 Main St, Worcester, MA 01609", college="<script>")
    assert "<script>" not in html.split("</select>", 1)[-1]
    assert 'id="college-heading"' not in html


def test_form_has_labeled_college_select(client):
    html = client.get("/check").text
    assert '<label for="college"' in html and 'id="college"' in html
    for c in COLLEGES:
        assert f'value="{c.id}"' in html
