"""Top-level pages: landing, about, and health."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.config import Settings, get_settings
from app.content.background import BACKGROUND
from app.content.sources import SOURCES
from app.services.boston import DATA_SOURCES
from app.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return templates.TemplateResponse(request, "index.html")


@router.get("/about", response_class=HTMLResponse)
def about(request: Request):
    return templates.TemplateResponse(
        request,
        "about.html",
        {"sources": list(SOURCES.values()), "data_sources": DATA_SOURCES, "background": BACKGROUND},
    )


@router.get("/health")
def health():
    # Liveness only. Which features are configured isn't public information.
    return {"status": "ok"}
