"""FastAPI entry point. Run with: uvicorn app.main:app --reload --no-access-log"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers, MutableHeaders
from starlette.formparsers import MultiPartParser
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.routers import check, pages, report, town
from app.services.pdf_text import MAX_PDF_BYTES
from app.templating import templates

STATIC_DIR = Path(__file__).parent / "static"

# Privacy: uvicorn's access log writes the client IP and full URL (including query strings
# like /report?address=...) for every request, which would let someone line up an IP with a
# tenant report. Turn it off here, at import, so it stays off however uvicorn is started.
_access_log = logging.getLogger("uvicorn.access")
_access_log.handlers.clear()
_access_log.propagate = False
_access_log.disabled = True

# Privacy: SDK and HTTP client debug logging can print request bodies, which include listing
# and lease text. Keep these at WARNING regardless of ANTHROPIC_LOG or root logger settings.
for _name in ("anthropic", "httpx", "httpx2", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

# Uploaded leases must never touch disk. Starlette spools uploads over 1 MB to a temp file,
# so raise the in-memory limit above our PDF limit. The size guard below rejects anything
# bigger before it's read, so this can't be used to fill memory.
MAX_REQUEST_BYTES = MAX_PDF_BYTES + 256 * 1024  # PDF plus form fields
MultiPartParser.spool_max_size = MAX_REQUEST_BYTES

TOO_LARGE_MESSAGE = "That upload is too large. The limit is 5 MB."
TOO_LONG_MESSAGE = "Some of what you entered is too long. Please shorten it and try again."


class _BodyTooLarge(Exception):
    pass


class LimitRequestSize:
    """Pure ASGI middleware that caps request bodies at max_bytes.

    Rejects up front when Content-Length is too big, and also counts bytes as they're received
    so chunked requests (no Content-Length) can't get past the limit.
    """

    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        await PlainTextResponse(TOO_LARGE_MESSAGE, status_code=413)(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        length = Headers(scope=scope).get("content-length")
        if length is not None and length.strip().isdigit() and int(length) > self.max_bytes:
            await self._reject(scope, receive, send)
            return

        received = 0
        too_large = False
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    too_large = True
                    raise _BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            # Once the body is over the limit, drop whatever the app tries to send (for example
            # an error response from the body parser); we send our own 413 below.
            if too_large and not response_started:
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _BodyTooLarge:
            pass
        except Exception:
            # The app may wrap our exception in its own (FastAPI turns body errors into 400s).
            if not too_large:
                raise
        if too_large and not response_started:
            await self._reject(scope, receive, send)


CDN_SCRIPTS = (
    "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.3/dist/index.global.js",
    "https://cdn.jsdelivr.net/npm/htmx.org@2.0.11/dist/htmx.min.js",
)

# Scripts only from this site and the two pinned, SRI-checked jsDelivr files; templates have no
# inline scripts or event-handler attributes. style-src needs 'unsafe-inline' because the
# Tailwind browser build and htmx inject <style> elements at runtime.
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        # Exact file paths, not the whole CDN host (must match the pinned tags in base.html).
        "script-src 'self' " + " ".join(CDN_SCRIPTS),
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)


class SecurityHeaders:
    """Pure ASGI middleware that adds security headers to every response.

    All responses: X-Content-Type-Options: nosniff, X-Frame-Options: DENY, and
    Referrer-Policy: strict-origin-when-cross-origin, plus CONTENT_SECURITY_POLICY. Town
    dashboard paths (/town...) instead get
    Referrer-Policy: no-referrer (building keys are in URLs) plus Cache-Control: no-store and
    Pragma: no-cache so signed-in pages aren't kept in shared or back-button caches.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        is_town = path == "/town" or path.startswith("/town/")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
                if is_town:
                    headers["Cache-Control"] = "no-store"
                    headers["Pragma"] = "no-cache"
                    headers["Referrer-Policy"] = "no-referrer"
                elif "referrer-policy" not in headers:
                    headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            await send(message)

        await self.app(scope, receive, send_with_headers)


app = FastAPI(title="TwoWaysOut", docs_url=None, redoc_url=None)
# add_middleware wraps outward: the size guard runs inside the header middleware, so its 413
# responses get the security headers too.
app.add_middleware(LimitRequestSize, max_bytes=MAX_REQUEST_BYTES)
app.add_middleware(SecurityHeaders)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    """Friendly error for over-length or malformed form input.

    FastAPI's default 422 JSON echoes the submitted values back, so never include them here.
    """
    if request.headers.get("HX-Request") == "true":
        # HTMX doesn't swap 4xx responses by default, so use 200 for the partial.
        return templates.TemplateResponse(
            request, "partials/check_error.html", {"error": TOO_LONG_MESSAGE}, status_code=200
        )
    path = request.url.path
    if path == "/check":
        return templates.TemplateResponse(
            request,
            "check.html",
            {"error": TOO_LONG_MESSAGE, "max_chars": check.MAX_CHARS, "address": "", "listing": ""},
            status_code=422,
        )
    if path == "/report":
        return report._form(request, status_code=422, error=TOO_LONG_MESSAGE)
    return templates.TemplateResponse(
        request, "error.html", {"error": TOO_LONG_MESSAGE}, status_code=422
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(pages.router)
app.include_router(check.router)
app.include_router(report.router)
app.include_router(town.router)
