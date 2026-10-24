"""Round 2: block_label edge cases never contain the original house number."""

import re

import pytest

from scripts.construction import block_label


def _tokens(label: str) -> set[str]:
    return set(re.split(r"[\s\-]+", label))


@pytest.mark.parametrize(
    "address, label",
    [
        # Letter suffixes, attached and on ranges.
        ("12A Mission Park DR", "1-99 block of Mission Park Dr"),
        ("31A-33B Boardman ST", "1-99 block of Boardman St"),
        ("12B-12C Main ST", "1-99 block of Main St"),
        ("182b London ST", "100 block of London St"),
        # Ranges: only the block of the first number, never either end of the range.
        ("31-33 Boardman ST", "1-99 block of Boardman St"),
        ("199-201 Main ST", "100 block of Main St"),
        ("181 - 183 State ST", "100 block of State St"),
        # Zero and zero-padded numbers.
        ("0 Main ST", "1-99 block of Main St"),
        ("00 Main ST", "1-99 block of Main St"),
        ("007 Elm ST", "1-99 block of Elm St"),
        # Numbered and lettered streets.
        ("12 5th ST", "1-99 block of 5TH St"),
        ("5 5th ST", "1-99 block of 5TH St"),
        ("182 182nd ST", "100 block of 182ND St"),
        ("12-14 W 3rd ST", "1-99 block of W 3RD St"),
        ("1 B ST", "1-99 block of B St"),
        # Large numbers and extra whitespace.
        ("1250 Commonwealth AV", "1200 block of Commonwealth Ave"),
        ("99999 Elm ST", "99900 block of Elm St"),
        ("  7  Elm ST ", "1-99 block of Elm St"),
    ],
)
def test_block_label_edge_cases(address, label):
    assert block_label(address) == label


@pytest.mark.parametrize(
    "address",
    [
        "12 Route 9",  # street ends in a number
        "12 Main ST #4",  # unit numbers
        "12 Main ST Unit 4",
        "12 Main ST Apt 3B",
        "12 Main ST 02128",  # trailing ZIP
        "12 Main ST, Boston, MA 02128",
        "Main ST",
        "",
        "   ",
        None,
        12,
    ],
)
def test_block_label_refuses_when_a_number_could_leak(address):
    assert block_label(address) is None


@pytest.mark.parametrize(
    "address, house_numbers",
    [
        ("12A Mission Park DR", ["12A", "12"]),
        ("31A-33B Boardman ST", ["31A", "33B", "31", "33"]),
        ("12B-12C Main ST", ["12B", "12C", "12"]),
        ("31-33 Boardman ST", ["31", "33"]),
        ("199-201 Main ST", ["199", "201"]),
        ("181 - 183 State ST", ["181", "183"]),
        ("0 Main ST", ["0"]),
        ("007 Elm ST", ["007", "7"]),
        ("12 5th ST", ["12"]),
        ("5 5th ST", ["5"]),
        ("182 182nd ST", ["182"]),
        ("12-14 W 3rd ST", ["12", "14"]),
        ("1250 Commonwealth AV", ["1250"]),
        ("99999 Elm ST", ["99999"]),
        ("184 London ST", ["184"]),
        ("186 London ST", ["186"]),
        ("230 London ST", ["230"]),
    ],
)
def test_block_label_never_contains_house_number(address, house_numbers):
    # Compared as whole tokens: "5TH" is the street, not house number 5. A house number that is
    # itself a multiple of 100 ("1200 Main") equals its block start by design, so none are here.
    toks = {t.upper() for t in _tokens(block_label(address))}
    for h in house_numbers:
        assert h.upper() not in toks, (address, h)


@pytest.mark.parametrize(
    "address",
    [
        "12 1/2 Main ST",  # fractional house number
        "12 14 Main ST",  # second number
        "12 & 14 Main ST",
        "12 to 14 Main ST",
        "1200 Rear 14 Main ST",
        "12 A Main ST",  # unit letter
        "12 Main ST Unit B",
        "12 Main ST 2nd FL",
        # Second privacy review: text after the street suffix, or punctuation.
        "12 Main St B",
        "12 Main St Bldg B",
        "12 Main St Unit:B",
        "12 Main St (Unit A)",
        "12 Main St (rear)",
        "12 Main St PH",
        "12 Main St Penthouse",
        "12 Main St A-B",
        "12 Main St L",
        "12 Main St Lower",
        "12 Main St Number Four",
        "12 Main St Garage",
        "12 Main St Dorchester",
    ],
)
def test_block_label_refuses_extra_address_parts(address):
    # Found in the privacy review: each of these used to keep part of the address.
    assert block_label(address) is None
