"""Address normalization shared by the preprocessing script and runtime lookups.

Both sides reduce a street name to the same key, e.g. "London Street" and "LONDON ST." -> "LONDON ST".
"""

import re
from dataclasses import dataclass

SUFFIXES = {
    "STREET": "ST", "STR": "ST", "ST": "ST",
    "AVENUE": "AVE", "AV": "AVE", "AVE": "AVE",
    "ROAD": "RD", "RD": "RD",
    "DRIVE": "DR", "DR": "DR",
    "PLACE": "PL", "PL": "PL",
    "TERRACE": "TER", "TERR": "TER", "TER": "TER",
    "COURT": "CT", "CT": "CT",
    "BOULEVARD": "BLVD", "BLVD": "BLVD",
    "PARKWAY": "PKWY", "PKWY": "PKWY",
    "SQUARE": "SQ", "SQ": "SQ",
    "CIRCLE": "CIR", "CIR": "CIR",
    "LANE": "LN", "LN": "LN",
    "HIGHWAY": "HWY", "HWY": "HWY",
    "WHARF": "WHF", "WHF": "WHF",
    "PLAZA": "PLZ", "PLZ": "PLZ",
    "ROW": "ROW", "WAY": "WAY", "PARK": "PARK",
}
DIRECTIONS = {"NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}
WORDS = {"MOUNT": "MT", "SAINT": "ST"}  # only applied as the first word of the street body

UNIT_MARKERS = r"(?:APT|APARTMENT|UNIT|STE|SUITE|FL|FLOOR|RM|ROOM|#)"
ZIP_RE = re.compile(r"\b(0\d{4})(?:-\d{4})?\b")
NUMBER_RE = re.compile(r"^\s*(\d+[A-Z]?)(?:\s*-\s*(\d+[A-Z]?))?\s+(.*)$")
BARE_UNIT_RE = re.compile(r"^(?:[A-Z]?\d+[A-Z]?(?:-\d*[A-Z]?)?|BSMT|BASEMENT|REAR|FRONT|PH|GRND)$")


def street_key(street: str) -> str:
    """Normalize a street name (no house number) to a comparison key."""
    s = re.sub(r"[.,']", "", street.upper())
    s = re.sub(r"\s+", " ", s).strip()
    words = s.split(" ") if s else []
    if not words:
        return ""
    if words[0] in DIRECTIONS and len(words) > 1:
        words[0] = DIRECTIONS[words[0]]
    first_body = 1 if words[0] in DIRECTIONS.values() and len(words) > 1 else 0
    if words[first_body] in WORDS and len(words) > first_body + 1:
        words[first_body] = WORDS[words[first_body]]
    if len(words) > 1 and words[-1] in SUFFIXES:
        words[-1] = SUFFIXES[words[-1]]
    elif len(words) > 2 and words[-1] in DIRECTIONS.values() | DIRECTIONS.keys() and words[-2] in SUFFIXES:
        words[-2] = SUFFIXES[words[-2]]
        words[-1] = DIRECTIONS.get(words[-1], words[-1])
    return " ".join(words)


_UPPER_TOKENS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}


def display_from_key(key: str) -> str:
    """Readable building-level address from a normalized key: "12 EXAMPLE ST 01002" -> "12 Example St 01002".

    Words are title-cased; house numbers, ZIPs, and compass directions ("E", "NW") are kept as is.
    """
    out = []
    for word in (key or "").split():
        if any(c.isdigit() for c in word) or word in _UPPER_TOKENS:
            out.append(word)
        else:
            # "O'NEIL" -> "O'Neil", "SMITH-JONES" -> "Smith-Jones"
            out.append(re.sub(r"[A-Za-z]+", lambda m: m.group().capitalize(), word))
    return " ".join(out)


def number_value(num: str | None) -> int | None:
    """'12A' -> 12, '181' -> 181."""
    if not num:
        return None
    m = re.match(r"\d+", str(num).strip())
    return int(m.group()) if m else None


@dataclass(frozen=True)
class ParsedAddress:
    number: str  # as typed, e.g. "12A" or "181-183"
    number_from: int
    number_to: int
    street: str  # normalized key, e.g. "LONDON ST"
    zip: str | None
    place: str | None  # city or neighborhood words, uppercased, if given


_SUFFIX_WORDS = "|".join(sorted({*SUFFIXES, *SUFFIXES.values()}, key=len, reverse=True))
ADDRESS_IN_TEXT = re.compile(
    rf"\b\d+[A-Za-z]?(?:\s*-\s*\d+[A-Za-z]?)?\s+(?:[A-Za-z][A-Za-z'.]*\s+){{1,4}}?(?:{_SUFFIX_WORDS})\b\.?"
    r"(?:\s*(?:,\s*)?(?:(?:apt|unit|#)\s*\w+))?"
    # Neighborhood/city: up to two comma-separated parts, or one capitalized word with no comma.
    r"(?:(?:\s*,\s*[A-Za-z][A-Za-z .]{1,30}){1,2}|(?-i:\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?))?"
    r"(?:\s*,?\s*(?:MA|Massachusetts))?"
    r"(?:\s*,?\s*0\d{4})?",
    re.IGNORECASE,
)


def find_address_in_text(text: str) -> str | None:
    """First street address in free text, e.g. a listing's 'Premises: 12 Example St, Unit 2, ...'."""
    for m in ADDRESS_IN_TEXT.finditer(text or ""):
        candidate = " ".join(m.group().split()).rstrip(" ,.")
        if parse_address(candidate):
            return candidate
    return None


def parse_address(text: str) -> ParsedAddress | None:
    """Parse '182 London St Apt 2, East Boston, MA 02128'. Returns None if there's no house number."""
    if not text:
        return None
    s = " ".join(text.upper().split())
    zip_match = ZIP_RE.search(s)
    zip_code = zip_match.group(1) if zip_match else None
    if zip_match:
        s = (s[: zip_match.start()] + s[zip_match.end():]).strip(" ,")

    parts = [p.strip() for p in s.split(",") if p.strip()]
    if not parts:
        return None
    first, rest = parts[0], parts[1:]

    # Drop unit info from the street part: "London St Apt 2", "London St #2", "London St Unit B".
    first = re.split(rf"\s+{UNIT_MARKERS}\b\.?\s*|\s+#\s*", first, maxsplit=1)[0]
    first = re.sub(r"[.]", "", first)

    m = NUMBER_RE.match(first)
    if not m:
        return None
    n1, n2, street = m.group(1), m.group(2), m.group(3)
    lo = number_value(n1)
    hi = number_value(n2) if n2 else lo
    if lo is None or not street.strip():
        return None

    # Bare unit after the street, with no "Apt" or "#": "E Broadway 3", "Riverway 352-1",
    # "Branch St Bsmt". Street names never end in a token with a digit.
    words = street.split()
    while len(words) > 1 and BARE_UNIT_RE.match(words[-1]):
        words.pop()
    street = " ".join(words)

    # No comma before the city: "26 Clayton St Dorchester MA". Split after the last street
    # suffix (keeping a trailing direction like "Ave N") and treat the rest as the place.
    trailing_place = None
    for i in range(len(words) - 1, 0, -1):
        if words[i] in SUFFIXES:
            cut = i + 1
            # Only a one-letter direction ("Ave N"); "St East Boston" is a neighborhood.
            if cut < len(words) and words[cut] in DIRECTIONS.values():
                cut += 1
            if cut < len(words):
                trailing_place = " ".join(words[cut:])
                street = " ".join(words[:cut])
            break

    # Remaining parts: unit ("APT 2"), city/neighborhood, state.
    if trailing_place:
        rest = [trailing_place, *rest]
    place_parts = []
    for p in rest:
        p = re.sub(r"\b(?:MA|MASS|MASSACHUSETTS)\b", "", p).strip()
        if not p or re.match(rf"^{UNIT_MARKERS}\b|^#", p):
            continue
        place_parts.append(p)

    return ParsedAddress(
        number=f"{n1}-{n2}" if n2 else n1,
        number_from=min(lo, hi),
        number_to=max(lo, hi),
        street=street_key(street),
        zip=zip_code,
        place=place_parts[0] if place_parts else None,
    )
