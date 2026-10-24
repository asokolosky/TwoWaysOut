"""Student flow: paste a listing or upload a lease PDF, get a fire-safety report."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.content.checklist import TOPICS
from app.content.samples import SAMPLE_LISTING
from app.content.sources import SOURCES
from app.services import rules_analyzer
from app.services.address_normalize import find_address_in_text
from app.services.ai_client import get_ai_client
from app.services.analyzer import NotARentalDocument, analyze_listing
from app.services.boston import (
    DATA_SOURCES,
    BuildingContext,
    context_for_address,
    get_boston_db,
    snapshot_date,
)
from app.services.building_questions import construction_questions, questions_for_context
from app.services.census import CensusContext, census_context
from app.services.construction import ConstructionContext, construction_context
from app.services.fire_categories import CATEGORIES
from app.services.pdf_text import MAX_PDF_BYTES, PdfError, extract_text
from app.services.rate_limit import RateLimiter
from app.services.relevance import NOT_A_LISTING_MESSAGE, looks_like_rental_text
from app.services.report_models import SafetyReport
from app.templating import templates

router = APIRouter()

MAX_ADDRESS_CHARS = 200
MAX_CHARS = rules_analyzer.MAX_LISTING_CHARS
MAX_LISTING_FORM_CHARS = 200_000
RATE_LIMIT_NOTICE = "You've run several checks in the last hour, so this is the basic keyword analysis."

_check_limiter: RateLimiter | None = None


def get_check_limiter(settings: Settings = Depends(get_settings)) -> RateLimiter:
    """Per-client limit on AI-backed checks. Keyed by a salted hash of the IP, in memory only."""
    global _check_limiter
    if _check_limiter is None or _check_limiter.limit != settings.check_ai_per_hour:
        _check_limiter = RateLimiter(settings.check_ai_per_hour, window_seconds=3600)
    return _check_limiter


def _area_context(address: str, boston: BuildingContext | None, boston_db: Path):
    snap = snapshot_date(boston_db)
    return (
        construction_context(address, boston, boston_db, snapshot_date=snap),
        census_context(address, boston, boston_db),
    )


def _report_context(
    report: SafetyReport,
    address: str,
    address_from_listing: bool,
    notes: list[str],
    boston: BuildingContext | None,
    construction: ConstructionContext | None = None,
    census: CensusContext | None = None,
) -> dict:
    building_qs = questions_for_context(boston, report.questions)
    construction_qs = construction_questions(construction)
    cited = report.cited_source_ids()
    for q in building_qs + construction_qs:
        if q.source_id not in cited:
            cited.append(q.source_id)
    return {
        "construction": construction,
        "construction_questions": construction_qs,
        "census": census,
        "report": report,
        "address": address,
        "address_from_listing": address_from_listing,
        "notes": notes,
        "topics": TOPICS,
        "sources": SOURCES,
        "cited_sources": [SOURCES[s] for s in cited],
        "ctx": boston,
        "building_questions": building_qs,
        "data_sources": DATA_SOURCES,
        "category_labels": {k: v[0] for k, v in CATEGORIES.items()},
    }


def _error(request: Request, message: str, address: str, listing: str, is_htmx: bool):
    template = "partials/check_error.html" if is_htmx else "check.html"
    return templates.TemplateResponse(
        request,
        template,
        {"error": message, "max_chars": MAX_CHARS, "address": address, "listing": listing},
        # HTMX doesn't swap 4xx responses by default, so use 200 for the partial.
        status_code=200 if is_htmx else 422,
    )


async def _read_upload(upload: UploadFile) -> bytes:
    """Read at most MAX_PDF_BYTES + 1 bytes so an oversized file is rejected without loading it all."""
    chunks, total = [], 0
    while chunk := await upload.read(64 * 1024):
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_PDF_BYTES:
            break
    return b"".join(chunks)


@router.get("/check", response_class=HTMLResponse)
def check_form(request: Request, sample: bool = False):
    return templates.TemplateResponse(
        request,
        "check.html",
        {"max_chars": MAX_CHARS, "listing": SAMPLE_LISTING if sample else ""},
    )


@router.post("/check", response_class=HTMLResponse)
async def check_submit(
    request: Request,
    # Hard cap well above MAX_CHARS so long pastes get truncated with a note instead of a
    # validation error. Still far below the request-size guard in app/main.py.
    listing: Annotated[str, Form(max_length=MAX_LISTING_FORM_CHARS)] = "",
    address: Annotated[str, Form(max_length=MAX_ADDRESS_CHARS)] = "",
    lease_pdf: Annotated[UploadFile | None, File()] = None,
    settings: Settings = Depends(get_settings),
    ai_client=Depends(get_ai_client),
    boston_db: Path = Depends(get_boston_db),
    limiter: RateLimiter = Depends(get_check_limiter),
):
    listing = listing.strip()
    address = address.strip()
    is_htmx = request.headers.get("HX-Request") == "true"
    notes: list[str] = []

    # Browsers send an empty file part when nothing is selected.
    if lease_pdf is not None and lease_pdf.filename:
        try:
            data = await _read_upload(lease_pdf)
            pdf_text = extract_text(data)
        except PdfError as exc:
            return _error(request, str(exc), address, listing, is_htmx)
        finally:
            await lease_pdf.close()
            data = None  # drop the bytes; nothing is stored

        notes.append("Lease PDF read. The file and its text weren't saved.")
        # Combine with any pasted text so nothing the student entered is ignored.
        listing = f"{listing}\n\n{pdf_text}".strip() if listing else pdf_text

    if not listing:
        return _error(
            request, "Paste the listing or lease text, or upload a lease PDF.", address, "", is_htmx
        )

    if len(listing) > MAX_CHARS:
        listing = listing[:MAX_CHARS]
        notes.append(
            f"The text was long, so only the first {MAX_CHARS:,} characters were checked."
        )

    # Off-topic text is rejected before the rate limiter, so it never uses up a check.
    if not looks_like_rental_text(listing[:MAX_CHARS]):
        return _error(request, NOT_A_LISTING_MESSAGE, address, "", is_htmx)

    # Only AI-backed checks count toward the limit. The IP is hashed with a per-process salt
    # inside the limiter and is never stored or logged.
    client_ip = request.client.host if request.client else "unknown"
    rate_limited = False
    used_slot = False
    if ai_client is not None:
        if limiter.allow(client_ip):
            used_slot = True
        else:
            rate_limited = True
            ai_client = None

    # analyze_listing makes a blocking HTTP call; run it in FastAPI's thread pool.
    try:
        report = await run_in_threadpool(
            analyze_listing,
            listing,
            client=ai_client,
            model=settings.anthropic_model,
            timeout=settings.ai_timeout_seconds,
        )
    except NotARentalDocument as exc:
        if used_slot:
            limiter.refund(client_ip)  # rejected as off-topic: don't count it
        # Don't echo back long pasted text; keep the form empty except for short input.
        return _error(request, exc.message, address, "", is_htmx)
    if rate_limited:
        report = report.model_copy(update={"fallback_reason": RATE_LIMIT_NOTICE})

    # Address for the Boston lookup: the form field, else one found in the listing
    # (by Claude, or by the keyword finder when AI isn't available).
    lookup_address = address or report.extracted_address or find_address_in_text(listing) or ""
    boston = await run_in_threadpool(context_for_address, lookup_address, boston_db)
    construction, census = await run_in_threadpool(_area_context, lookup_address, boston, boston_db)
    ctx = _report_context(
        report,
        address=lookup_address,
        address_from_listing=bool(lookup_address) and not address,
        notes=notes,
        boston=boston,
        construction=construction,
        census=census,
    )

    # HTMX swaps just the report into the page; without JS, render the full page.
    template = "partials/report.html" if is_htmx else "report_page.html"
    return templates.TemplateResponse(request, template, ctx)
