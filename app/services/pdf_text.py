"""Extract text from an uploaded lease PDF, entirely in memory. Nothing is written to disk."""

import io
import logging

from pypdf import PdfReader

log = logging.getLogger(__name__)

MAX_PDF_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_PDF_PAGES = 30
# Below this many letters, assume a scanned (image-only) PDF.
MIN_TEXT_CHARS = 40


class PdfError(Exception):
    """A problem the student can fix. The message is shown on the page."""


def extract_text(data: bytes) -> str:
    if len(data) > MAX_PDF_BYTES:
        raise PdfError("That PDF is larger than 5 MB. Try a smaller file or paste the text instead.")
    if not data.lstrip()[:5] == b"%PDF-":
        raise PdfError("That file isn't a PDF. Upload a PDF lease or paste the text instead.")

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            # Many leases are "encrypted" with an empty password just to block editing.
            if not reader.decrypt(""):
                raise PdfError(
                    "That PDF is password-protected. Remove the password or paste the text instead."
                )
        page_count = len(reader.pages)
        if page_count > MAX_PDF_PAGES:
            raise PdfError(
                f"That PDF has {page_count} pages. The limit is {MAX_PDF_PAGES}. "
                "Paste the sections about the unit, safety, and repairs instead."
            )
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
    except PdfError:
        raise
    except Exception as exc:  # pypdf raises many types for damaged files
        log.info("PDF could not be read: %s", type(exc).__name__)
        raise PdfError("That PDF couldn't be read. Try another copy or paste the text instead.") from exc

    text = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if sum(ch.isalpha() for ch in text) < MIN_TEXT_CHARS:
        raise PdfError(
            "This PDF looks like a scan, so there's no text to read. "
            "Copy the text from the original lease and paste it instead."
        )
    return text
