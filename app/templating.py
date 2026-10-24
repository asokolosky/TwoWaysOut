"""Shared Jinja2 environment so every router renders with the same globals."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.content.colleges import COLLEGES
from app.content.copy import DISCLAIMER, RANKING_STATEMENT

TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals.update(
    DISCLAIMER=DISCLAIMER,
    RANKING_STATEMENT=RANKING_STATEMENT,
    COLLEGES=sorted(COLLEGES, key=lambda c: c.name),
)
