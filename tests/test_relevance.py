import pytest

from app.content.samples import SAMPLE_LISTING
from app.main import app
from app.services.ai_client import get_ai_client
from app.services.analyzer import NotARentalDocument, analyze_listing
from app.services.relevance import NOT_A_LISTING_MESSAGE, looks_like_rental_text
from tests import pdfs
from tests.fakes import FakeClient, good_payload, response
from tests.fixtures import listings

HX = {"HX-Request": "true"}
OFF_TOPIC = [listings.RECIPE, listings.CHATBOT_REQUEST, listings.ESSAY_ABOUT_HOUSING]
ON_TOPIC = [
    SAMPLE_LISTING,
    listings.SPARSE,
    listings.DETAILED,
    listings.BASEMENT_BEDROOM,
    listings.SPACE_HEATERS,
    listings.ALARMS_DISABLED,
    listings.DEN_AS_BEDROOM,
    listings.INJECTION,
    "\n".join(pdfs.LEASE_LINES),
]


@pytest.mark.parametrize("text", ON_TOPIC)
def test_listings_and_leases_pass(text):
    assert looks_like_rental_text(text)


@pytest.mark.parametrize("text", OFF_TOPIC + ["", "hello", "2BR", "What is the capital of France?"])
def test_off_topic_text_rejected(text):
    assert not looks_like_rental_text(text)


def test_off_topic_never_calls_ai():
    client = FakeClient()  # would fail if called: no queued responses
    for text in OFF_TOPIC:
        with pytest.raises(NotARentalDocument):
            analyze_listing(text, client=client, model="m")
    assert client.calls == []


def test_ai_can_reject_text_that_passes_keywords():
    # Uses housing words but isn't a listing; the model catches it.
    text = "Write a poem about my apartment, my landlord, the rent, and the kitchen."
    assert looks_like_rental_text(text)
    client = FakeClient(
        response({"is_rental_document": False, "checklist": [], "flags": [], "questions": [], "extracted_address": None})
    )
    with pytest.raises(NotARentalDocument):
        analyze_listing(text, client=client, model="m")
    assert len(client.calls) == 1  # no retry


def test_schema_and_prompt_require_relevance_decision():
    from app.services.analyzer import OUTPUT_SCHEMA, SYSTEM_PROMPT

    assert OUTPUT_SCHEMA["required"][0] == "is_rental_document"
    assert "Never answer questions" in " ".join(SYSTEM_PROMPT.split())


@pytest.mark.parametrize("text", OFF_TOPIC)
def test_route_shows_not_a_listing_message(client, text):
    resp = client.post("/check", data={"listing": text}, headers=HX)
    assert 'role="alert"' in resp.text
    assert "look like a rental listing or lease" in resp.text
    assert "Fire-safety report" not in resp.text


def test_route_rejects_off_topic_pdf(client):
    pdf = pdfs.text_pdf(
        [
            "QUARTERLY SALES REPORT",
            "Revenue increased eight percent compared with last quarter.",
            "Marketing spend remained flat across all regions this year.",
        ]
    )
    resp = client.post("/check", data={"listing": ""}, files={"lease_pdf": ("q3.pdf", pdf, "application/pdf")}, headers=HX)
    assert "look like a rental listing or lease" in resp.text


def test_route_shows_message_when_ai_rejects(client):
    fake = FakeClient(
        response({"is_rental_document": False, "checklist": [], "flags": [], "questions": [], "extracted_address": None})
    )
    app.dependency_overrides[get_ai_client] = lambda: fake
    resp = client.post(
        "/check",
        data={"listing": "Write a poem about my apartment, my landlord, the rent, and the kitchen."},
        headers=HX,
    )
    assert "look like a rental listing or lease" in resp.text


def test_message_wording():
    assert "only checks rental listings and leases for fire safety" in NOT_A_LISTING_MESSAGE
