"""Checklist "why" text claims only what its one linked source supports."""
from app.content.checklist import TOPICS


def test_smoke_alarm_why_sticks_to_the_smoke_alarm_rules():
    info = TOPICS["smoke_alarms"]
    assert info.source_id == "smoke_alarm_rules"
    why = info.why.lower()
    assert "smoke alarms in every home" in why
    # CO requirements live in co_alarm_rules (fossil-fuel equipment or enclosed parking only).
    assert "carbon monoxide" not in why
    assert "most homes" not in why


def test_smoke_alarm_check_page_text(client):
    from tests.fixtures.listings import SPARSE

    html = client.post("/check", data={"listing": SPARSE}, headers={"HX-Request": "true"}).text
    assert TOPICS["smoke_alarms"].why in html
    assert "alarms in most homes" not in html
