"""Saving tenant hazard reports. User submissions are always is_simulated = 0."""

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.content.report_categories import REPORT_CATEGORIES
from app.db import connect
from app.services.address import AddressMatch, lookup
from app.services.address_normalize import parse_address

MAX_ADDRESS_CHARS = 200
MAX_DESCRIPTION_CHARS = 1000
EARLIEST_OBSERVED = date(2000, 1, 1)

# Emails, including spaces around "@" ("jane @ umass.edu").
EMAIL_RE = re.compile(r"[\w.+-]+\s*@\s*[\w-]+(?:\.[\w-]+)+")
# Obfuscated emails ("jane at umass dot edu", "jane [at] umass [dot] edu"). Only matches
# name at domain dot tld with a common TLD, so "alarm at the front door" is left alone.
_AT = r"\s*[\[(]?\s*at\s*[\])]?\s*"
_DOT = r"\s*[\[(]?\s*dot\s*[\])]?\s*"
_TLD = r"(?:com|edu|org|net|gov|mil|io|co|us|uk|ca|me|info|biz)"
OBFUSCATED_EMAIL_RE = re.compile(
    rf"\b[\w.+-]+{_AT}[\w-]+(?:{_DOT}[\w-]+)*?{_DOT}{_TLD}\b", re.IGNORECASE
)
# International numbers starting with "+" ("+44 20 7946 0958"); checked for 8+ digits below.
INTL_PHONE_RE = re.compile(r"(?<![\w+])\+\d{1,3}(?:[ .-]?\(?\d{1,4}\)?){2,5}(?!\d)")
# North American numbers: (617) 555-0123, 617.555.0199, 617 - 555 - 1234, 617/555-1234, +1 413 555 0100.
# The lookbehind keeps it from starting inside a longer number or a date like 2026-10-01.
PHONE_RE = re.compile(
    r"(?<![\w+])(?:\+?1(?:\s*[-.]\s*|\s+)?)?"
    r"(?:\(\s*\d{3}\s*\)|\d{3})(?:\s*[-./]\s*|\s+)?"
    r"\d{3}(?:\s*[-.]\s*|\s+)?\d{4}(?!\d)"
)
# 7-digit local numbers ("555-1234"). A "-" or "." separator is required so years (2024) and
# street numbers (1234) aren't touched.
LOCAL_PHONE_RE = re.compile(r"(?<![\w+\-./])\d{3}\s*[-.]\s*\d{4}(?![\w-])")
# Social handles ("@jane_doe"). Runs after emails are removed.
HANDLE_RE = re.compile(r"(?<![\w@.])@[A-Za-z_][\w.]*\w")


class ReportError(ValueError):
    """Validation problem shown to the person submitting."""


@dataclass(frozen=True)
class SavedReport:
    id: int
    category_labels: tuple[str, ...]  # most serious first
    department: str
    match: AddressMatch
    in_boston: bool
    redacted: bool

    @property
    def category_label(self) -> str:
        return "; ".join(self.category_labels)


def order_categories(selected: str | list[str] | tuple[str, ...]) -> list[str]:
    """Validate selected problem types and order them most serious first.

    A submission is scored once, at its most serious problem, so checking every box can't
    inflate a building's ranking. The others are kept for hazard labels and filtering.
    """
    if isinstance(selected, str):
        selected = [selected]
    ids = list(dict.fromkeys(s for s in (selected or []) if s))  # dedupe, keep order
    if not ids or any(i not in REPORT_CATEGORIES for i in ids):
        raise ReportError("Choose what kind of problem you're reporting.")
    order = list(REPORT_CATEGORIES)
    return sorted(ids, key=lambda i: (-REPORT_CATEGORIES[i].severity, order.index(i)))


def split_categories(category: str, extra: str | None) -> list[str]:
    """All problem types for a stored report: the scored one first, then the others."""
    return [category] + [c for c in (extra or "").split(",") if c and c != category]


def redact_contact_info(text: str) -> tuple[str, bool]:
    """Remove emails, phone numbers, and social handles so reports stay anonymous."""
    cleaned = _redact_emails_and_phones(text)
    cleaned = HANDLE_RE.sub("[handle removed]", cleaned)
    return cleaned, cleaned != text


def _redact_intl(m: re.Match) -> str:
    return "[phone removed]" if sum(c.isdigit() for c in m.group()) >= 8 else m.group()


def _redact_emails_and_phones(text: str) -> str:
    # Emails first so digits inside an address aren't read as a phone number.
    cleaned = EMAIL_RE.sub("[email removed]", text)
    cleaned = OBFUSCATED_EMAIL_RE.sub("[email removed]", cleaned)
    cleaned = INTL_PHONE_RE.sub(_redact_intl, cleaned)
    cleaned = PHONE_RE.sub("[phone removed]", cleaned)
    return LOCAL_PHONE_RE.sub("[phone removed]", cleaned)


def has_contact_info(text: str) -> bool:
    """True if the text contains an email address or phone number."""
    return _redact_emails_and_phones(text) != text


def address_key(address: str, match: AddressMatch) -> str | None:
    """Groups reports for the same building, even outside Boston where there's no parcel."""
    if match.matched and match.parcel_id:
        return f"PARCEL {match.parcel_id}"
    return text_key(address)


def text_key(address: str) -> str | None:
    """Building-level "NUMBER STREET ZIP" (or place) key. Unit numbers and other extra text are dropped."""
    p = parse_address(address)
    if p is None:
        return None
    return " ".join(x for x in (p.number, p.street, p.zip or (p.place or "")) if x)


def parse_observed(value: str | None) -> str | None:
    if not value:
        return None
    try:
        d = date.fromisoformat(value)
    except ValueError as exc:
        raise ReportError("Enter the date as YYYY-MM-DD, or leave it blank.") from exc
    if d > date.today():
        raise ReportError("The date you noticed the problem can't be in the future.")
    if d < EARLIEST_OBSERVED:
        raise ReportError("That date is too far in the past.")
    return d.isoformat()


def save_report(
    app_db: Path,
    boston_db: Path,
    *,
    address: str,
    category: str | list[str],
    description: str = "",
    observed_date: str | None = None,
) -> SavedReport:
    address = " ".join((address or "").split())
    if not address:
        raise ReportError("Enter the address of the building.")
    if len(address) > MAX_ADDRESS_CHARS:
        raise ReportError("That address is too long.")
    if has_contact_info(address):
        # Rejected rather than silently edited, so the saved address is what the person typed.
        raise ReportError("Leave contact information out of the address.")
    if parse_address(address) is None:
        raise ReportError("Include the street number, like “12 Example St.”")
    categories = order_categories(category)
    description = (description or "").strip()
    if len(description) > MAX_DESCRIPTION_CHARS:
        raise ReportError(f"Keep the description under {MAX_DESCRIPTION_CHARS:,} characters.")
    description, redacted = redact_contact_info(description)
    observed = parse_observed(observed_date)

    match = lookup(address, boston_db)
    # sqlite3's context manager only commits; closing() also releases the connection.
    with closing(connect(app_db)) as con, con:
        cur = con.execute(
            """INSERT INTO reports (address_input, address_key, display_address, parcel_id, sam_id,
                                    ward, zip, category, extra_categories, description,
                                    observed_date, created_at, is_simulated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                address,
                address_key(address, match),
                match.display_address if match.matched else None,
                match.parcel_id if match.matched else None,
                match.sam_id if match.matched else None,
                match.ward if match.matched else None,
                match.zip if match.matched else (parse_address(address).zip),
                categories[0],
                ",".join(categories[1:]) or None,
                description or None,
                observed,
                # Day precision only, set explicitly so older tables with a timestamp default
                # still store just the date.
                date.today().isoformat(),
            ),
        )
        report_id = cur.lastrowid
    cat = REPORT_CATEGORIES[categories[0]]
    return SavedReport(
        id=report_id,
        category_labels=tuple(REPORT_CATEGORIES[c].label for c in categories),
        department=cat.department,
        match=match,
        # Decides which "what happens next" links to show (Boston 311 vs. local Board of Health).
        in_boston=match.matched or match.reason in ("not_found", "ambiguous"),
        redacted=redacted,
    )


def count_reports(app_db: Path, *, simulated: bool | None = None) -> int:
    with closing(sqlite3.connect(app_db)) as con:
        if simulated is None:
            return con.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        return con.execute("SELECT COUNT(*) FROM reports WHERE is_simulated = ?", (int(simulated),)).fetchone()[0]
