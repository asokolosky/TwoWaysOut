from app.config import Settings, get_settings
from app.content.copy import DISCLAIMER, RANKING_STATEMENT
from app.main import app


def test_landing_page_has_both_entry_points(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'href="/check"' in resp.text
    assert 'href="/town"' in resp.text
    assert "Check a rental" in resp.text
    assert "For towns &amp; cities" in resp.text


def test_landing_page_basic_accessibility(client):
    html = client.get("/").text
    assert '<html lang="en">' in html
    assert 'href="#main"' in html  # skip link
    assert 'id="main"' in html


def test_sections_load(client):
    assert client.get("/check").status_code == 200
    # No dashboard password in test settings, so the town dashboard explains how to set it up.
    town = client.get("/town")
    assert town.status_code == 503
    assert "Dashboard isn't configured" in town.text


def test_health_is_status_only(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_never_reveals_configuration_or_secrets(client):
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        anthropic_api_key="sk-test-secret",
        dashboard_password="pw-secret",
        session_secret="session-secret",
    )
    resp = client.get("/health")
    assert resp.json() == {"status": "ok"}
    for secret in ("sk-test-secret", "pw-secret", "session-secret", "configured"):
        assert secret not in resp.text


def test_fixed_copy_is_exact():
    assert DISCLAIMER == (
        "This is general information, not legal advice. "
        "Contact your local Board of Health to request an inspection."
    )
    assert RANKING_STATEMENT == "Rankings reflect reported problems, not predicted fire risk"


def test_about_background_facts_each_have_a_linked_source(client):
    from app.content.background import BACKGROUND

    html = client.get("/about").text
    assert "Figures as cited by the project" not in html
    for item in BACKGROUND:
        assert item.sources
        for src in item.sources:
            assert src.url.startswith("https://")
            assert f'href="{src.url}"' in html
    assert html.count("(opens in a new tab)") >= sum(len(i.sources) for i in BACKGROUND)
