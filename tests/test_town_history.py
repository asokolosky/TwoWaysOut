"""Town dashboard: signed-in HTML stays out of htmx's localStorage history cache, and ranking
never reads area-level or outreach-only data."""
import ast
import re
from pathlib import Path

from app.services import ranking
from tests.test_town import (  # noqa: F401  (fixtures are used by name)
    LONDON,
    boston_db,
    csrf_from,
    login,
    seeded,
    town,
    town_limiter,
)

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"
BODY_RE = re.compile(r"<body\b[^>]*>", re.I)


def _body_tag(html: str) -> str:
    m = BODY_RE.search(html)
    assert m, "no <body> tag"
    return m.group(0)


def test_signed_in_town_pages_disable_htmx_history(town, seeded):
    login(town)
    paths = ("/town", "/town?zip=02128", f"/town/building?key=PARCEL%20{LONDON}", "/town/simulated/SIM-01")
    for path in paths:
        resp = town.get(path)
        assert resp.status_code == 200, path
        assert 'hx-history="false"' in _body_tag(resp.text), path


def test_signed_out_town_pages_disable_htmx_history(town):
    resp = town.get("/town/login")
    assert 'hx-history="false"' in _body_tag(resp.text)


def test_every_town_template_disables_htmx_history():
    for f in sorted(TEMPLATES.glob("town_*.html")):
        assert '{% block body_attrs %} hx-history="false"{% endblock %}' in f.read_text(), f.name


def test_public_pages_keep_htmx_history(client):
    # Only town pages opt out; the public pages keep normal back-button behavior.
    for path in ("/", "/check", "/report", "/about"):
        assert "hx-history" not in _body_tag(client.get(path).text), path


def test_logout_clears_cache_and_storage(town):
    login(town)
    token = csrf_from(town.get("/town").text)
    resp = town.post("/town/logout", data={"csrf_token": token}, follow_redirects=False)
    assert resp.status_code == 303
    directives = {d.strip() for d in resp.headers["clear-site-data"].split(",")}
    assert directives == {'"cache"', '"storage"'}


def test_ranking_never_reads_area_or_outreach_data():
    """Area stats, Census data, and nearby construction are display or outreach only."""
    src = Path(ranking.__file__).read_text()
    for name in ("area_stats", "census_zip", "census", "construction", "datacommons"):
        assert name not in src.lower(), name
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    banned = {"app.services.census", "app.services.construction"}
    assert not imported & banned, imported & banned
