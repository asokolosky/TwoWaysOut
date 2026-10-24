"""Town dashboard: password login, ranked real buildings, masked simulated reports, and an
inspection status workflow.

Auth: a shared DASHBOARD_PASSWORD and a signed, HttpOnly session cookie scoped to /town
(see app/services/town_auth.py). Every state-changing POST needs a CSRF token tied to the session.
Without both settings the dashboard is closed (503); it never opens without a password.
"""
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.content.report_categories import REPORT_CATEGORIES
from app.db import get_app_db
from app.services import town_auth
from app.services.boston import DATA_SOURCES, get_boston_db, history_for_parcel, snapshot_date
from app.services.building_status import STATUS_LABELS, STATUSES, get_status, get_statuses, set_status
from app.services.fire_categories import CATEGORIES as FIRE_CATEGORIES
from app.services.ranking import (
    HALF_LIFE_DAYS,
    OFFICIAL_CAP,
    OPEN_VIOLATION_POINTS,
    RECENT_RECORD_POINTS,
    building_reports,
    rank_real_buildings,
    rank_simulated,
)
from app.services.rate_limit import RateLimiter
from app.templating import templates

router = APIRouter(prefix="/town")

LOGIN_PATH = "/town/login"
DEFAULT_LIMIT = 50
MAX_LIMIT = 2000
LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 15 * 60
WRONG_PASSWORD = "That password isn't right."
TOO_MANY_ATTEMPTS = "Too many sign-in attempts. Please wait 15 minutes and try again."
CSRF_HEADER = "X-CSRF-Token"
ZIP_RE = re.compile(r"^\d{5}$")
SIM_RE = re.compile(r"^SIM-[A-Za-z0-9_-]{1,40}$")

_login_limiter: RateLimiter | None = None


def get_login_limiter() -> RateLimiter:
    """Failed sign-in attempts per (hashed) client IP. Overridden in tests."""
    global _login_limiter
    if _login_limiter is None:
        _login_limiter = RateLimiter(LOGIN_ATTEMPTS, window_seconds=LOGIN_WINDOW_SECONDS)
    return _login_limiter


# Filter choices: tenant report categories, then Boston fire categories not already covered.
CATEGORY_OPTIONS: list[tuple[str, str]] = [(c.id, c.label) for c in REPORT_CATEGORIES.values()] + [
    (cid, f"{label} (any source)") for cid, (label, _topic) in FIRE_CATEGORIES.items()
]
CATEGORY_IDS = {cid for cid, _ in CATEGORY_OPTIONS}

templates.env.globals.update(TOWN_STATUS_LABELS=STATUS_LABELS)


# --- Auth helpers -------------------------------------------------------------------------


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _not_configured(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "town_not_configured.html", {}, status_code=503)


def _to_login(request: Request) -> Response:
    if _is_htmx(request):
        # HTMX follows HX-Redirect with a full page load instead of swapping a login form in.
        return Response(status_code=200, headers={"HX-Redirect": LOGIN_PATH})
    return RedirectResponse(LOGIN_PATH, status_code=303)


def _session(request: Request, settings: Settings, app_db: Path) -> tuple[str, int] | None:
    """(nonce, issued_at) for a genuine, unexpired, not signed-out session cookie."""
    info = town_auth.session_info(settings.session_secret or "", request.cookies.get(town_auth.SESSION_COOKIE))
    if info is None or town_auth.is_revoked(app_db, info[0]):
        return None
    return info


def _guard(request: Request, settings: Settings, app_db: Path) -> tuple[str | None, Response | None]:
    """(nonce, None) when signed in; (None, response) to return otherwise."""
    if not town_auth.is_configured(settings):
        return None, _not_configured(request)
    info = _session(request, settings, app_db)
    if info is None:
        return None, _to_login(request)
    return info[0], None


def _secure_cookie(request: Request, settings: Settings) -> bool:
    return request.url.scheme == "https" or settings.force_secure_cookies


def _csrf_ok(request: Request, settings: Settings, nonce: str, form_token: str) -> bool:
    supplied = form_token or request.headers.get(CSRF_HEADER, "")
    return town_auth.check_csrf(settings.session_secret or "", nonce, supplied)


def _forbidden(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "error.html",
        {"error": "This form expired. Reload the page and try again."},
        status_code=403,
    )


def _render(request: Request, name: str, ctx: dict, settings: Settings, nonce: str, status_code: int = 200):
    ctx = {**ctx, "csrf_token": town_auth.csrf_token(settings.session_secret or "", nonce), "signed_in": True}
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def building_url(key: str) -> str:
    return "/town/building?key=" + quote(key, safe="")


templates.env.globals.update(town_building_url=building_url)


# --- Login and logout ---------------------------------------------------------------------


def _login_page(request: Request, *, error: str | None = None, status_code: int = 200):
    return templates.TemplateResponse(request, "town_login.html", {"error": error}, status_code=status_code)


@router.get("/login", response_class=HTMLResponse)
def login_form(
    request: Request,
    settings: Settings = Depends(get_settings),
    app_db: Path = Depends(get_app_db),
):
    if not town_auth.is_configured(settings):
        return _not_configured(request)
    if _session(request, settings, app_db):
        return RedirectResponse("/town", status_code=303)
    return _login_page(request)


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    password: Annotated[str, Form(max_length=1_000)] = "",
    settings: Settings = Depends(get_settings),
    limiter: RateLimiter = Depends(get_login_limiter),
):
    if not town_auth.is_configured(settings):
        return _not_configured(request)
    # The limiter hashes the IP in memory; it's never stored or logged.
    client_ip = request.client.host if request.client else "unknown"
    # Reserve an attempt atomically before checking, so concurrent guesses can't slip past the
    # limit; a correct password gives it back, so only failures count.
    if not limiter.allow(client_ip):
        return _login_page(request, error=TOO_MANY_ATTEMPTS, status_code=429)
    if not town_auth.check_password(settings, password):
        return _login_page(request, error=WRONG_PASSWORD, status_code=401)
    limiter.refund(client_ip)
    response = RedirectResponse("/town", status_code=303)
    response.set_cookie(
        town_auth.SESSION_COOKIE,
        town_auth.issue_session(settings.session_secret),
        max_age=town_auth.SESSION_MAX_AGE,
        path="/town",
        httponly=True,
        samesite="lax",
        secure=_secure_cookie(request, settings),
    )
    return response


@router.post("/logout")
def logout(
    request: Request,
    csrf_token: Annotated[str, Form(max_length=200)] = "",
    settings: Settings = Depends(get_settings),
    app_db: Path = Depends(get_app_db),
):
    if not town_auth.is_configured(settings):
        return _not_configured(request)
    info = _session(request, settings, app_db)
    if info is None:
        return _to_login(request)
    nonce, issued_at = info
    if not _csrf_ok(request, settings, nonce, csrf_token):
        return _forbidden(request)
    # Revoke server-side so a copied cookie stops working, not just this browser's copy.
    town_auth.revoke_session(app_db, nonce, issued_at)
    response = RedirectResponse(LOGIN_PATH, status_code=303)
    response.delete_cookie(
        town_auth.SESSION_COOKIE,
        path="/town",
        httponly=True,
        samesite="lax",
        secure=_secure_cookie(request, settings),
    )
    # "storage" also clears localStorage, where htmx keeps page snapshots for the back button.
    response.headers["Clear-Site-Data"] = '"cache", "storage"'
    return response


# --- Dashboard ----------------------------------------------------------------------------


def _clean_filters(zip_code: str, category: str) -> tuple[str | None, str | None, str | None]:
    zip_code = zip_code.strip()
    error = None
    if zip_code and not ZIP_RE.match(zip_code):
        error = "Enter a 5-digit ZIP code."
        zip_code = ""
    return zip_code or None, category if category in CATEGORY_IDS else None, error


def _results_context(app_db: Path, boston_db: Path, zip_code: str | None, category: str | None, limit: int, error):
    ranked = rank_real_buildings(app_db, boston_db, zip_code=zip_code, category=category)
    shown = ranked[:limit]
    statuses = get_statuses(app_db, [b.building_key for b in shown])
    query = {"zip": zip_code or "", "category": category or ""}
    more_qs = "&".join(f"{k}={quote(v)}" for k, v in query.items() if v)
    return {
        "buildings": shown,
        "total_count": len(ranked),
        "statuses": statuses,
        "zip": zip_code or "",
        "category": category or "",
        "limit": limit,
        "more_url": f"/town?{more_qs + '&' if more_qs else ''}limit={min(limit + DEFAULT_LIMIT, MAX_LIMIT)}",
        "has_more": len(ranked) > limit and limit < MAX_LIMIT,
        "filter_error": error,
        "category_options": CATEGORY_OPTIONS,
    }


@router.get("", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    zip: Annotated[str, Query(max_length=20)] = "",
    category: Annotated[str, Query(max_length=50)] = "",
    limit: Annotated[int, Query(ge=1)] = DEFAULT_LIMIT,
    settings: Settings = Depends(get_settings),
    app_db: Path = Depends(get_app_db),
    boston_db: Path = Depends(get_boston_db),
):
    nonce, blocked = await run_in_threadpool(_guard, request, settings, app_db)
    if blocked is not None:
        return blocked
    zip_code, cat, error = _clean_filters(zip, category)
    limit = min(limit, MAX_LIMIT)
    ctx = await run_in_threadpool(_results_context, app_db, boston_db, zip_code, cat, limit, error)
    if _is_htmx(request) and request.headers.get("HX-Target") == "town-results":
        return _render(request, "partials/town_results.html", ctx, settings, nonce)
    ctx.update(
        simulated=await run_in_threadpool(rank_simulated, app_db),
        snapshot_date=snapshot_date(boston_db),
        data_sources=DATA_SOURCES,
        half_life=HALF_LIFE_DAYS,
        official_cap=OFFICIAL_CAP,
        open_points=OPEN_VIOLATION_POINTS,
        recent_points=RECENT_RECORD_POINTS,
    )
    return _render(request, "town_dashboard.html", ctx, settings, nonce)


# --- Building detail and status -----------------------------------------------------------


def _find_building(app_db: Path, boston_db: Path, key: str):
    return next((b for b in rank_real_buildings(app_db, boston_db) if b.building_key == key), None)


def _not_found(request: Request, settings: Settings, nonce: str, what: str = "building"):
    return _render(request, "town_not_found.html", {"what": what}, settings, nonce, status_code=404)


@router.get("/building", response_class=HTMLResponse)
async def building_detail(
    request: Request,
    key: Annotated[str, Query(max_length=300)] = "",
    settings: Settings = Depends(get_settings),
    app_db: Path = Depends(get_app_db),
    boston_db: Path = Depends(get_boston_db),
):
    nonce, blocked = await run_in_threadpool(_guard, request, settings, app_db)
    if blocked is not None:
        return blocked
    building = await run_in_threadpool(_find_building, app_db, boston_db, key) if key else None
    if building is None:
        return _not_found(request, settings, nonce)
    reports = await run_in_threadpool(building_reports, app_db, key)
    # Privacy rule 2: official history only for likely rentals.
    history = None
    if building.is_boston_rental and building.parcel_id:
        history = await run_in_threadpool(history_for_parcel, building.parcel_id, boston_db)
    ctx = {
        "b": building,
        "reports": reports,
        "history": history,
        "status": get_status(app_db, key),
        "statuses": STATUSES,
        "data_sources": DATA_SOURCES,
    }
    return _render(request, "town_building.html", ctx, settings, nonce)


@router.post("/building/status", response_class=HTMLResponse)
async def building_status_update(
    request: Request,
    key: Annotated[str, Form(max_length=300)] = "",
    status: Annotated[str, Form(max_length=20)] = "",
    csrf_token: Annotated[str, Form(max_length=200)] = "",
    settings: Settings = Depends(get_settings),
    app_db: Path = Depends(get_app_db),
    boston_db: Path = Depends(get_boston_db),
):
    nonce, blocked = await run_in_threadpool(_guard, request, settings, app_db)
    if blocked is not None:
        return blocked
    if not _csrf_ok(request, settings, nonce, csrf_token):
        return _forbidden(request)
    if status not in STATUSES:
        return _render(
            request, "error.html", {"error": "Choose open, scheduled, or inspected."}, settings, nonce, status_code=422
        )
    building = await run_in_threadpool(_find_building, app_db, boston_db, key) if key else None
    if building is None:
        return _not_found(request, settings, nonce)
    saved = await run_in_threadpool(set_status, app_db, key, status)
    if _is_htmx(request):
        ctx = {"b": building, "status": saved, "statuses": STATUSES, "saved_message": True}
        return _render(request, "partials/town_status.html", ctx, settings, nonce)
    return RedirectResponse(building_url(key), status_code=303)


# --- Simulated detail (masked) ------------------------------------------------------------


def _simulated_reports(app_db: Path, sim_building: str) -> list[dict]:
    if not app_db.exists():
        return []
    # Read-only: this view never writes.
    with closing(sqlite3.connect(f"file:{app_db}?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """SELECT category, description, observed_date, created_at FROM simulated_reports
               WHERE sim_building = ? ORDER BY COALESCE(observed_date, created_at) DESC, id DESC""",
            (sim_building,),
        ).fetchall()
    out = []
    for r in rows:
        cat = REPORT_CATEGORIES.get(r["category"], REPORT_CATEGORIES["other"])
        out.append(
            {
                "category_label": cat.label,
                "description": r["description"],
                "month": (r["observed_date"] or r["created_at"] or "")[:7] or None,
            }
        )
    return out


@router.get("/simulated/{sim_building}", response_class=HTMLResponse)
async def simulated_detail(
    request: Request,
    sim_building: str,
    settings: Settings = Depends(get_settings),
    app_db: Path = Depends(get_app_db),
):
    nonce, blocked = await run_in_threadpool(_guard, request, settings, app_db)
    if blocked is not None:
        return blocked
    if not SIM_RE.match(sim_building):
        return _not_found(request, settings, nonce, what="simulated report")
    sims = await run_in_threadpool(rank_simulated, app_db)
    sim = next((s for s in sims if s.sim_building == sim_building), None)
    if sim is None:
        return _not_found(request, settings, nonce, what="simulated report")
    reports = await run_in_threadpool(_simulated_reports, app_db, sim_building)
    return _render(request, "town_simulated.html", {"sim": sim, "reports": reports}, settings, nonce)
