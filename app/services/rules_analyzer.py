"""Keyword-based listing analyzer. Works with no API key and is the fallback for the AI analyzer.

For each topic it looks for concern phrases first (e.g. "no smoke detectors", "basement bedroom"),
then for phrases showing the listing addresses the topic. It never concludes a unit "is safe":
the best status is "mentioned", which the UI shows as "verify in person".
"""

import re
from dataclasses import dataclass

from app.content.questions import QUESTION_BANK
from app.services.report_models import (
    SEVERITY_RANK,
    TOPIC_ORDER,
    ChecklistItem,
    Flag,
    LandlordQuestion,
    SafetyReport,
    Status,
)

MAX_LISTING_CHARS = 20_000
EVIDENCE_CHARS = 200


@dataclass(frozen=True)
class Rule:
    tag: str  # used to pick follow-up questions
    pattern: re.Pattern


def _r(tag: str, pattern: str) -> Rule:
    return Rule(tag, re.compile(pattern, re.IGNORECASE))


ALARM = r"(?:smoke|fire)\s*(?:alarm|detector)s?"
CO = r"(?:carbon\s+monoxide|\bco\b)\s*(?:alarm|detector)s?"

CONCERN_RULES: dict[str, list[Rule]] = {
    "smoke_alarms": [
        _r("alarm_missing", rf"\b(?:no|without|missing|lacks?)\s+(?:working\s+)?(?:{ALARM}|{CO})"),
        _r("alarm_missing", rf"(?:{ALARM}|{CO})\s+(?:\w+\s+){{0,3}}(?:removed|disabled|disconnected|missing|covered|not\s+working|broken|beeping)"),
    ],
    "two_ways_out": [
        _r("basement_attic", r"\b(?:basement|attic|cellar)\s+(?:bed)?room\b"),
        _r("basement_attic", r"\bbed(?:room)?s?\s+(?:is\s+|are\s+)?(?:in|on)\s+the\s+(?:basement|attic|cellar)\b"),
        _r("basement_attic", r"\b(?:finished|converted)\s+(?:basement|attic)\b[^.\n]{0,60}\b(?:bed|sleep)"),
        _r("extra_sleeping", r"\b(?:den|loft|office|bonus\s+room|study|sunroom|closet)\b[^.\n]{0,50}\b(?:used\s+as|use\s+as|works\s+as|could\s+be|can\s+be)\s+(?:an?\s+)?(?:extra\s+|\d+(?:st|nd|rd|th)\s+)?bed(?:room)?"),
        _r("extra_sleeping", r"\b(?:extra|additional|5th|6th)\s+(?:bed)?room\b[^.\n]{0,40}\b(?:no\s+window|windowless|interior)"),
        _r("one_exit", r"\b(?:only\s+one|single|one)\s+(?:exit|entrance|entry|way\s+(?:in|out)|stair(?:way|case)?)\b"),
        _r("one_exit", r"\bno\s+(?:fire\s+escape|second\s+(?:exit|stair(?:way|case)?)|rear\s+(?:exit|stairs?|door))\b"),
        _r("one_exit", r"\b(?:windowless|no\s+windows?)\b[^.\n]{0,30}\bbed(?:room)?"),
        _r("one_exit", r"\bbed(?:room)?s?\b[^.\n]{0,30}\b(?:windowless|no\s+windows?)\b"),
        _r("blocked_exit", r"\b(?:exit|stair(?:way|s)?|fire\s+escape|back\s+door|hallway)\s+(?:is\s+|are\s+)?(?:blocked|used\s+for\s+storage|nailed\s+shut|locked)\b"),
    ],
    "sprinklers": [
        _r("no_sprinklers", r"\b(?:no|without)\s+(?:automatic\s+|fire\s+)?sprinklers?\b"),
        _r("no_sprinklers", r"\bnot\s+sprinklered\b|\bunsprinklered\b"),
    ],
    "heating": [
        _r("space_heaters", r"\bspace\s+heaters?\b|\bportable\s+heaters?\b|\belectric\s+heaters?\s+(?:provided|included)\b"),
        _r("no_heat", r"\bno\s+heat\b|\bheat(?:ing)?\s+(?:doesn'?t|does\s+not|isn'?t|is\s+not)\s+(?:work|working|reach)"),
        _r("no_heat", r"\b(?:bedroom|room)s?\s+(?:\w+\s+){0,3}(?:gets?|can\s+get|is|are)\s+(?:cold|chilly)\b"),
    ],
    "electrical": [
        _r("old_wiring", r"\bknob[\s-]+and[\s-]+tube\b|\bfuse\s*box\b|\bfuses\b"),
        _r("few_outlets", r"\b(?:few|limited|not\s+many|one|only\s+one)\s+(?:electrical\s+)?outlets?\b|\boutlets?\s+(?:are\s+)?limited\b"),
        _r("extension_cords", r"\bextension\s+cords?\b|\bpower\s+strips?\b"),
        _r("tripping", r"\b(?:breakers?|circuits?)\s+(?:\w+\s+){0,2}trips?\b|\btrips?\s+(?:the\s+)?(?:breaker|circuit)"),
    ],
}

MENTION_RULES: dict[str, list[Rule]] = {
    "smoke_alarms": [
        _r("alarm", ALARM),
        _r("co_alarm", CO),
        _r("alarm", r"\bfire\s+alarm\s+system\b|\bhard[\s-]?wired\b[^.\n]{0,20}\balarm"),
    ],
    "two_ways_out": [
        _r("second_exit", r"\bfire\s+escapes?\b"),
        _r("second_exit", r"\b(?:second|rear|back|two)\s+(?:exits?|egress|stair(?:way|case)?s?|entrances?|means\s+of\s+egress)\b"),
        _r("second_exit", r"\b(?:back|rear)\s+(?:door|porch|deck)\b"),
        _r("second_exit", r"\begress\s+windows?\b|\btwo\s+ways\s+out\b"),
    ],
    "sprinklers": [
        _r("sprinklers", r"\bsprinkler(?:s|ed)?\b|\bsprinkler\s+system\b"),
    ],
    "heating": [
        _r("fuel_heat", r"\b(?:gas|oil|natural\s+gas|propane)\s+(?:heat|heating|furnace|boiler)\b"),
        _r("heat", r"\b(?:forced[\s-]air|baseboard|radiant|steam|hot[\s-]water|central|electric)\s+heat(?:ing)?\b"),
        _r("heat", r"\bheat\s+(?:is\s+)?included\b|\bheat\s+pumps?\b|\bmini[\s-]?splits?\b|\bradiators?\b|\bfurnace\b|\bboiler\b"),
    ],
    "electrical": [
        _r("updated", r"\b(?:new|updated|upgraded|modern|renovated)\s+(?:electrical|wiring|electric\s+panel|panel)\b"),
        _r("updated", r"\b(?:electrical|wiring)\s+(?:\w+\s+){0,2}(?:updated|upgraded|replaced|new)\b|\brewired\b"),
        _r("breakers", r"\bcircuit\s+breakers?\b|\bbreaker\s+(?:panel|box)\b|\b(?:100|150|200)[\s-]?amp\b"),
        _r("outlets", r"\b(?:plenty\s+of|lots\s+of|many|ample)\s+outlets\b"),
    ],
}

def _evidence(text: str, match: re.Match) -> str:
    """The sentence (or line) containing the match, trimmed to EVIDENCE_CHARS."""
    start = max(text.rfind(c, 0, match.start()) for c in ".!?\n") + 1
    ends = [i for i in (text.find(c, match.end()) for c in ".!?\n") if i != -1]
    end = min(ends) + 1 if ends else len(text)
    snippet = " ".join(text[start:end].split())
    if len(snippet) > EVIDENCE_CHARS:
        snippet = snippet[: EVIDENCE_CHARS - 1].rstrip() + "…"
    return snippet


def _first_matches(text: str, rules: list[Rule]) -> tuple[set[str], str | None]:
    tags: set[str] = set()
    evidence = None
    for rule in rules:
        m = rule.pattern.search(text)
        if m:
            tags.add(rule.tag)
            if evidence is None:
                evidence = _evidence(text, m)
    return tags, evidence


FLAG_TEXT = {
    # (topic, status) -> (severity, message)
    ("smoke_alarms", Status.CONCERN): ("high", "The listing suggests smoke or carbon monoxide alarms are missing or not working."),
    ("smoke_alarms", Status.NOT_MENTIONED): ("medium", "The listing doesn't mention smoke or carbon monoxide alarms."),
    ("two_ways_out", Status.CONCERN): ("high", "Some sleeping space may not have a second way out."),
    ("two_ways_out", Status.NOT_MENTIONED): ("medium", "The listing doesn't say whether bedrooms and the unit have a second way out."),
    ("sprinklers", Status.CONCERN): ("medium", "The listing says the building has no sprinklers."),
    ("sprinklers", Status.NOT_MENTIONED): ("low", "The listing doesn't mention sprinklers."),
    ("heating", Status.CONCERN): ("medium", "The listing suggests the main heat may not be enough, or that space heaters are used."),
    ("heating", Status.NOT_MENTIONED): ("low", "The listing doesn't describe the heating system."),
    ("electrical", Status.CONCERN): ("medium", "The listing suggests old wiring, too few outlets, or heavy use of extension cords."),
    ("electrical", Status.NOT_MENTIONED): ("low", "The listing doesn't mention the electrical system."),
}


def _questions_for(topic: str, status: Status, tags: set[str]) -> list[str]:
    missing = status is not Status.MENTIONED
    keys: list[str] = []
    if topic == "smoke_alarms":
        keys.append("smoke_every_level")
        keys.append("co_every_level")
        if missing:
            keys.append("owner_maintains_alarms")
    elif topic == "two_ways_out":
        keys.append("bedroom_two_ways")
        if "basement_attic" in tags:
            keys.append("basement_attic_bedroom")
        if "extra_sleeping" in tags:
            keys.append("extra_sleeping_room")
        if missing:
            keys.append("unit_second_exit")
        if "blocked_exit" in tags:
            keys.append("exits_clear")
    elif topic == "sprinklers":
        if missing:
            keys.append("sprinklers")
    elif topic == "heating":
        if "space_heaters" in tags:
            keys.append("space_heaters")
        elif missing:
            keys.append("heat_every_room")
    elif topic == "electrical":
        keys.append("enough_outlets")
        if missing:
            keys.append("wiring_maintained")
    return keys


def analyze(text: str) -> SafetyReport:
    text = (text or "")[:MAX_LISTING_CHARS]
    checklist: list[ChecklistItem] = []
    flags: list[Flag] = []
    question_keys: list[str] = []

    for topic in TOPIC_ORDER:
        concern_tags, concern_ev = _first_matches(text, CONCERN_RULES[topic])
        mention_tags, mention_ev = _first_matches(text, MENTION_RULES[topic])

        if concern_tags:
            status, evidence = Status.CONCERN, concern_ev
        elif mention_tags:
            status, evidence = Status.MENTIONED, mention_ev
        else:
            status, evidence = Status.NOT_MENTIONED, None

        checklist.append(ChecklistItem(topic=topic, status=status, evidence=evidence))

        if (topic, status) in FLAG_TEXT:
            severity, message = FLAG_TEXT[(topic, status)]
            flags.append(Flag(topic=topic, severity=severity, message=message, evidence=evidence))

        for key in _questions_for(topic, status, concern_tags | mention_tags):
            if key not in question_keys:
                question_keys.append(key)

    questions: list[LandlordQuestion] = [QUESTION_BANK[k] for k in question_keys]
    flags.sort(key=lambda f: SEVERITY_RANK[f.severity])
    return SafetyReport(analyzer="rules", checklist=checklist, flags=flags, questions=questions)
