"""Tenant hazard reports: an anonymous form and a confirmation page."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.content.report_categories import BOSTON_311_URL, BOSTON_ISD_URL, REPORT_CATEGORIES
from app.db import get_app_db
from app.services.boston import get_boston_db
from app.services.rate_limit import RateLimiter
from app.services.reports import MAX_ADDRESS_CHARS, MAX_DESCRIPTION_CHARS, ReportError, save_report
from app.templating import templates

router = APIRouter()

_limiter: RateLimiter | None = None


def get_report_limiter(settings: Settings = Depends(get_settings)) -> RateLimiter:
    global _limiter
    if _limiter is None or _limiter.limit != settings.reports_per_hour:
        _limiter = RateLimiter(settings.reports_per_hour, window_seconds=3600)
    return _limiter


def _form(request: Request, *, status_code: int = 200, **ctx):
    defaults = {
        "categories": REPORT_CATEGORIES,
        "max_address": MAX_ADDRESS_CHARS,
        "max_description": MAX_DESCRIPTION_CHARS,
        "address": "",
        "category": [],
        "description": "",
        "observed_date": "",
        "error": None,
    }
    return templates.TemplateResponse(request, "report_form.html", {**defaults, **ctx}, status_code=status_code)


@router.get("/report", response_class=HTMLResponse)
def report_form(request: Request, address: str = ""):
    # Prefilled from "Report a problem here" on a student report.
    return _form(request, address=address[:MAX_ADDRESS_CHARS])


@router.post("/report", response_class=HTMLResponse)
async def report_submit(
    request: Request,
    # Generous hard caps here; save_report enforces the real limits with friendly messages.
    address: Annotated[str, Form(max_length=2_000)] = "",
    # Checkboxes: one value per selected problem. save_report validates each one.
    category: Annotated[list[str], Form()] = [],
    description: Annotated[str, Form(max_length=10_000)] = "",
    observed_date: Annotated[str, Form(max_length=200)] = "",
    website: Annotated[str, Form(max_length=200)] = "",  # honeypot: hidden from people
    app_db: Path = Depends(get_app_db),
    boston_db: Path = Depends(get_boston_db),
    limiter: RateLimiter = Depends(get_report_limiter),
):
    # There are only a few problem types; a request with many more values is malformed.
    if len(category) > len(REPORT_CATEGORIES):
        category = ["__too_many__"]  # fails validation below with the normal message
    # Only known ids are echoed back to re-check the boxes after an error.
    checked = [c for c in category if c in REPORT_CATEGORIES]
    values = {"address": address, "category": checked, "description": description, "observed_date": observed_date}

    if website:
        # Bots fill every field. Show the normal confirmation without saving anything.
        return templates.TemplateResponse(request, "report_thanks.html", {"saved": None})

    # The limiter hashes the IP with a per-process salt; it's never stored or logged.
    client_ip = request.client.host if request.client else "unknown"
    if not limiter.allow(client_ip):
        return _form(
            request,
            status_code=429,
            error="You've sent several reports in the last hour. Please try again later.",
            **values,
        )

    try:
        saved = await run_in_threadpool(
            save_report,
            app_db,
            boston_db,
            address=address,
            category=category,
            description=description,
            observed_date=observed_date or None,
        )
    except ReportError as exc:
        # A rejected submission saves nothing, so it doesn't use up one of the hourly reports.
        limiter.refund(client_ip)
        return _form(request, status_code=422, error=str(exc), **values)

    return templates.TemplateResponse(
        request,
        "report_thanks.html",
        {"saved": saved, "boston_311_url": BOSTON_311_URL, "boston_isd_url": BOSTON_ISD_URL},
    )
