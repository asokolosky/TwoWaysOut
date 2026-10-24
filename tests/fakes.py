"""Fake Anthropic client for tests. Never touches the network."""

import json
from types import SimpleNamespace


def response(payload, stop_reason="end_turn"):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[
            SimpleNamespace(type="thinking", thinking="..."),
            SimpleNamespace(type="text", text=text),
        ],
    )


class FakeClient:
    """Returns (or raises) the queued items in order, one per messages.create call."""

    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def good_payload(**overrides):
    payload = {
        "checklist": [
            {"topic": "smoke_alarms", "status": "not_mentioned", "evidence": None},
            {"topic": "two_ways_out", "status": "concern", "evidence": "finished basement bedroom with its own entrance"},
            {"topic": "sprinklers", "status": "not_mentioned", "evidence": None},
            {"topic": "heating", "status": "concern", "evidence": "Two space heaters provided for the back bedrooms"},
            {"topic": "electrical", "status": "not_mentioned", "evidence": None},
        ],
        "flags": [
            {"topic": "heating", "severity": "medium", "message": "Space heaters suggest the main heat may not reach the back bedrooms.", "evidence": None},
            {"topic": "two_ways_out", "severity": "high", "message": "The basement bedroom may not have a second way out.", "evidence": None},
        ],
        "questions": [
            {"topic": "two_ways_out", "question": "Does the basement bedroom have a window large enough to climb out of?", "source_id": "amherst_fire", "relation": "based_on"},
            {"topic": "smoke_alarms", "question": "Is there a smoke alarm in the basement bedroom?", "source_id": "smoke_alarm_rules", "relation": "required_by"},
            {"topic": "smoke_alarms", "question": "With a gas stove, is there a carbon monoxide alarm on each level?", "source_id": "co_alarm_rules", "relation": "required_by"},
            {"topic": "heating", "question": "Why are space heaters needed in the back bedrooms?", "source_id": "sanitary_code", "relation": "required_by"},
            {"topic": "sprinklers", "question": "Does the building have sprinklers?", "source_id": "umass_off_campus", "relation": "based_on"},
            {"topic": "electrical", "question": "When was the wiring in this 1910 building last updated?", "source_id": "sanitary_code", "relation": "required_by"},
        ],
        "extracted_address": None,
    }
    payload.update(overrides)
    return payload
