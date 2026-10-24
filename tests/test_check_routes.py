import re

from app.content.copy import DISCLAIMER
from tests.fixtures import listings

SECTION_NUMBER = re.compile(r"\d+\s*CMR|§", re.IGNORECASE)
HX = {"HX-Request": "true"}


def test_check_form_renders(client):
    resp = client.get("/check")
    assert resp.status_code == 200
    assert 'name="listing"' in resp.text
    assert 'name="address"' in resp.text
    assert '<label for="listing"' in resp.text


def test_sample_prefills_listing(client):
    resp = client.get("/check?sample=1")
    assert "triple-decker" in resp.text


def test_htmx_submit_returns_report_partial(client):
    resp = client.post("/check", data={"listing": listings.BASEMENT_BEDROOM}, headers=HX)
    assert resp.status_code == 200
    assert "<html" not in resp.text  # partial only
    assert "Fire-safety report" in resp.text
    assert "Basic analysis" in resp.text
    assert "Questions to ask the landlord" in resp.text
    assert "Required by the Massachusetts State Sanitary Code" in resp.text
    assert DISCLAIMER in resp.text


def test_no_js_submit_returns_full_page(client):
    resp = client.post("/check", data={"listing": listings.SPARSE, "address": "1 Main St"})
    assert resp.status_code == 200
    assert "<html" in resp.text
    assert "For: 1 Main St" in resp.text
    assert DISCLAIMER in resp.text


def test_rendered_report_has_no_section_numbers(client):
    for text in (listings.SPARSE, listings.SPACE_HEATERS, listings.INJECTION):
        html = client.post("/check", data={"listing": text}, headers=HX).text
        # Strip URLs and the echoed listing evidence; check only our own copy.
        visible = re.sub(r'href="[^"]*"', "", html)
        visible = re.sub(r"<q[^>]*>.*?</q>", "", visible, flags=re.S)
        assert not SECTION_NUMBER.search(visible)


def test_listing_text_is_escaped(client):
    evil = '2BR apartment. No smoke detectors <script>alert("x")</script>.'
    html = client.post("/check", data={"listing": evil}, headers=HX).text
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_empty_listing_shows_error(client):
    resp = client.post("/check", data={"listing": "   "}, headers=HX)
    assert resp.status_code == 200
    assert 'role="alert"' in resp.text
    resp = client.post("/check", data={"listing": ""})
    assert resp.status_code == 422


def test_long_listing_is_truncated_with_note(client):
    text = listings.SPARSE + "\n" + "x" * (20_001 - len(listings.SPARSE) - 1)
    assert len(text) == 20_001
    resp = client.post("/check", data={"listing": text}, headers=HX)
    assert resp.status_code == 200
    assert "Fire-safety report" in resp.text
    assert "only the first 20,000 characters were checked" in resp.text


def test_oversized_listing_rejected_without_echo(client):
    marker = "UNIQUEMARKER"
    text = (marker + " ") * (300_000 // (len(marker) + 1) + 1)
    assert len(text) > 300_000
    resp = client.post("/check", data={"listing": text})
    assert resp.status_code == 422
    assert "<html" in resp.text and 'role="alert"' in resp.text
    assert "Some of what you entered is too long" in resp.text
    assert marker not in resp.text

    resp = client.post("/check", data={"listing": text}, headers=HX)
    assert resp.status_code == 200
    assert "<html" not in resp.text
    assert "Some of what you entered is too long" in resp.text
    assert marker not in resp.text


# --- AI analyzer wired into the route -----------------------------------------------------

def test_route_uses_ai_client_when_available(client):
    from app.main import app
    from app.services.ai_client import get_ai_client
    from tests.fakes import FakeClient, good_payload, response

    fake = FakeClient(response(good_payload(extracted_address="12 Example St")))
    app.dependency_overrides[get_ai_client] = lambda: fake
    html = client.post("/check", data={"listing": listings.BASEMENT_BEDROOM}, headers=HX).text
    assert "AI analysis" in html
    assert "12 Example St" in html and "found in the listing" in html
    assert DISCLAIMER in html


def test_route_shows_fallback_notice(client):
    from app.main import app
    from app.services.ai_client import get_ai_client
    from tests.fakes import FakeClient, response

    fake = FakeClient(response("bad"), response("bad"))
    app.dependency_overrides[get_ai_client] = lambda: fake
    html = client.post("/check", data={"listing": listings.SPARSE}, headers=HX).text
    assert "Basic analysis" in html
    assert "AI analysis wasn&#39;t available" in html
    assert DISCLAIMER in html
