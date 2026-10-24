from app.content.sources import SOURCES
from app.services.report_models import TOPIC_ORDER, Status
from app.services.rules_analyzer import MAX_LISTING_CHARS, analyze
from tests.fixtures import listings


def statuses(report):
    return {item.topic: item.status for item in report.checklist}


def question_text(report):
    return " ".join(q.question for q in report.questions)


def test_report_always_covers_all_five_topics_in_order():
    for text in (listings.SPARSE, listings.DETAILED, ""):
        report = analyze(text)
        assert [i.topic for i in report.checklist] == list(TOPIC_ORDER)
        assert report.analyzer == "rules"


def test_sparse_listing_nothing_mentioned():
    report = analyze(listings.SPARSE)
    assert set(statuses(report).values()) == {Status.NOT_MENTIONED}
    assert len(report.flags) == 5
    # Missing info produces questions for every topic.
    assert {q.topic for q in report.questions} == set(TOPIC_ORDER)


def test_detailed_listing_everything_mentioned_never_safe():
    report = analyze(listings.DETAILED)
    assert set(statuses(report).values()) == {Status.MENTIONED}
    assert report.flags == []
    # Still asks the core verification questions.
    assert any(q.topic == "smoke_alarms" for q in report.questions)
    assert any(q.topic == "two_ways_out" for q in report.questions)
    assert "safe" not in question_text(report).lower()


def test_basement_bedroom_is_a_concern():
    report = analyze(listings.BASEMENT_BEDROOM)
    s = statuses(report)
    assert s["two_ways_out"] == Status.CONCERN
    assert s["smoke_alarms"] == Status.MENTIONED
    assert s["heating"] == Status.MENTIONED
    assert "basement or attic bedroom" in question_text(report)
    top = report.flags[0]
    assert top.topic == "two_ways_out" and top.severity == "high"


def test_space_heaters_and_old_wiring():
    report = analyze(listings.SPACE_HEATERS)
    s = statuses(report)
    assert s["heating"] == Status.CONCERN
    assert s["electrical"] == Status.CONCERN
    assert "space heaters" in question_text(report)
    heating = next(i for i in report.checklist if i.topic == "heating")
    assert "Space heaters" in heating.evidence


def test_disabled_alarms_and_no_sprinklers():
    report = analyze(listings.ALARMS_DISABLED)
    s = statuses(report)
    assert s["smoke_alarms"] == Status.CONCERN
    assert s["sprinklers"] == Status.CONCERN
    assert s["two_ways_out"] == Status.MENTIONED  # fire escape
    assert report.flags[0].severity == "high"


def test_den_used_as_bedroom():
    report = analyze(listings.DEN_AS_BEDROOM)
    assert statuses(report)["two_ways_out"] == Status.CONCERN
    assert "den, loft" in question_text(report)


def test_questions_unique_and_sourced():
    for text in vars(listings).values():
        if not isinstance(text, str) or text.startswith("Fictional"):
            continue
        report = analyze(text)
        qs = [q.question for q in report.questions]
        assert len(qs) == len(set(qs))
        assert all(q.source_id in SOURCES for q in report.questions)


def test_injection_text_is_just_data():
    report = analyze(listings.INJECTION)
    assert report.analyzer == "rules"
    assert all(q.source_id in SOURCES for q in report.questions)
    assert statuses(report)["smoke_alarms"] == Status.NOT_MENTIONED


def test_very_long_input_is_truncated():
    text = "x" * (MAX_LISTING_CHARS + 50) + " no smoke detectors"
    # The concern phrase is past the limit, so it's ignored.
    assert statuses(analyze(text))["smoke_alarms"] == Status.NOT_MENTIONED
