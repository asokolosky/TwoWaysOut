"""Tag Boston violation and complaint descriptions with a fire-safety category.

Rules were written against the real description strings in RentSmart and ISD Building
Violations (October 2026 snapshot). Order matters: the first matching rule wins.
Records that match no rule (trash, rodents, snow, permits) aren't fire-related and are dropped.
"""

import re

# Category -> how it's labeled in the UI, and which report checklist topic it relates to.
CATEGORIES = {
    "smoke_alarms": ("Smoke and carbon monoxide alarms", "smoke_alarms"),
    "egress": ("Exits and ways out", "two_ways_out"),
    "fire_protection": ("Sprinklers and fire protection", "sprinklers"),
    "heating": ("Heating", "heating"),
    "electrical": ("Electrical", "electrical"),
}

# Utility billing, metering, and shutoffs mention electricity or heat but aren't about the
# condition of the equipment. Exhaust "outlets" are vents, not electrical outlets.
EXCLUDE = re.compile(
    r"meter(?:ed|ing|s)?\b|sub-metering|provide the (?:electricity|oil)|provisions? of oil"
    r"|utility is sep[ae]rated|pay for electricity|shutoff|failure to restore"
    r"|no utilities|exhaust outlets",
    re.IGNORECASE,
)

RULES: list[tuple[str, re.Pattern]] = [
    ("smoke_alarms", re.compile(r"smoke|carbon monoxide|\bco\s+(?:alarm|detector)|fire\s+(?:alarm|warning)|automatic smoke", re.I)),
    ("heating", re.compile(r"\bheat|heating|boiler|furnace|space heater|temperature requirements|combust fuel|vented to the outdoors", re.I)),
    ("egress", re.compile(r"egress|\bexits?\b|exit (?:access|signs?|passageways?|stairways?)|fire escape|emergency lighting|passageway", re.I)),
    ("fire_protection", re.compile(r"sprinkler|fire protection|fire (?:separation|walls?|partitions?|blocking|stop|resistance|extinguishers?)|fire-resistance|fire and smoke protection|horozontal assemblies;\s*fire", re.I)),
    ("electrical", re.compile(r"electric|wiring|live parts|receptacle outlets|distribution panel|amperage", re.I)),
]


def categorize(description: str | None) -> str | None:
    if not isinstance(description, str) or not description or EXCLUDE.search(description):
        return None
    for category, pattern in RULES:
        if pattern.search(description):
            return category
    return None


LEGAL_REFERENCE = re.compile(
    r"\b(?:as\s+)?(?:required|prohibited|defined)\s+(?:by|in|under)\b"
    r"|\b\d+\s*CMR\b|\bM\.?\s*G\.?\s*L\b|§|\b\d{3}\.\d+",
    re.IGNORECASE,
)


def display_description(description: str, limit: int = 160) -> str:
    """Short, readable description with no regulation or section numbers.

    Cuts the text at the first legal reference ("as required by 105 CMR ...", "M.G.L.",
    "§", "410.170"), since what follows is citation detail.
    """
    text = " ".join(description.split())
    m = LEGAL_REFERENCE.search(text)
    if m:
        text = text[: m.start()]
    text = re.sub(r"[\s,;:(\-]+$", "", text)
    text = re.sub(r"\s+is\s+required$", "", text, flags=re.I)
    text = re.sub(r"\s+(?:or|and|the|as|in|of|to|by|with|under)$", "", text, flags=re.I).rstrip(" ,;:")
    if len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return text
