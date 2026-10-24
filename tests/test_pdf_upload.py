import pytest

from app.content.copy import DISCLAIMER
from app.main import MAX_REQUEST_BYTES, app
from app.services.ai_client import get_ai_client
from app.services.pdf_text import MAX_PDF_BYTES, PdfError, extract_text
from tests import pdfs
from tests.fakes import FakeClient, good_payload, response

HX = {"HX-Request": "true"}


def upload(client, data: bytes, name="lease.pdf", ctype="application/pdf", listing="", headers=HX):
    return client.post(
        "/check",
        data={"listing": listing, "address": ""},
        files={"lease_pdf": (name, data, ctype)},
        headers=headers,
    )


# --- Extraction ---------------------------------------------------------------------------

def test_extracts_text_from_pdf():
    text = extract_text(pdfs.text_pdf(pdfs.LEASE_LINES))
    assert "basement" in text
    assert "space heaters" in text


@pytest.mark.parametrize(
    "data, message",
    [
        (b"%PDF-" + b"0" * MAX_PDF_BYTES, "larger than 5 MB"),
        (b"PK\x03\x04 this is a zip file", "isn't a PDF"),
        (b"%PDF-1.4\ngarbage that is not a real pdf", "couldn't be read"),
    ],
)
def test_bad_files_rejected(data, message):
    with pytest.raises(PdfError, match=message):
        extract_text(data)


def test_scanned_pdf_rejected():
    with pytest.raises(PdfError, match="looks like a scan"):
        extract_text(pdfs.blank_pdf(2))


def test_too_many_pages_rejected():
    with pytest.raises(PdfError, match="31 pages"):
        extract_text(pdfs.blank_pdf(31))


def test_empty_password_pdf_is_read():
    assert "basement" in extract_text(pdfs.encrypted_pdf(""))


def test_password_protected_pdf_rejected():
    with pytest.raises(PdfError, match="password-protected"):
        extract_text(pdfs.encrypted_pdf("secret"))


# --- Route --------------------------------------------------------------------------------

def test_upload_produces_report(client):
    resp = upload(client, pdfs.text_pdf(pdfs.LEASE_LINES))
    assert resp.status_code == 200
    html = resp.text
    assert "Fire-safety report" in html
    assert "Lease PDF read" in html
    # Rule analyzer picks up the basement bedroom and space heaters from the PDF.
    assert "basement" in html
    assert "space heaters" in html
    assert DISCLAIMER in html


def test_upload_without_js_returns_full_page(client):
    resp = upload(client, pdfs.text_pdf(pdfs.LEASE_LINES), headers={})
    assert resp.status_code == 200
    assert "<html" in resp.text and "Fire-safety report" in resp.text


def test_pdf_text_sent_to_ai(client):
    fake = FakeClient(response(good_payload()))
    app.dependency_overrides[get_ai_client] = lambda: fake
    upload(client, pdfs.text_pdf(pdfs.LEASE_LINES), listing="Pasted note about the porch.")
    content = fake.calls[0]["messages"][0]["content"]
    assert "Pasted note about the porch." in content
    assert "gas boiler" in content


@pytest.mark.parametrize(
    "data, name, ctype, message",
    [
        # Just over the PDF limit but under the request limit: rejected by the PDF check.
        (b"%PDF-" + b"0" * (MAX_PDF_BYTES + 10), "big.pdf", "application/pdf", "larger than 5 MB"),
        (b"just some text", "notes.txt", "text/plain", "isn&#39;t a PDF"),
        (pdfs.blank_pdf(1), "scan.pdf", "application/pdf", "looks like a scan"),
        (pdfs.blank_pdf(31), "long.pdf", "application/pdf", "31 pages"),
    ],
)
def test_upload_errors_shown(client, data, name, ctype, message):
    resp = upload(client, data, name=name, ctype=ctype)
    assert resp.status_code == 200
    assert 'role="alert"' in resp.text
    assert message in resp.text
    assert "Fire-safety report" not in resp.text


def test_upload_error_without_js_keeps_pasted_text(client):
    resp = upload(client, b"nope", name="x.pdf", listing="My pasted listing", headers={})
    assert resp.status_code == 422
    assert "My pasted listing" in resp.text


def test_no_file_selected_uses_pasted_text(client):
    # Browsers send an empty part with no filename when no file is chosen.
    resp = upload(client, b"", name="", ctype="application/octet-stream", listing="2BR, no smoke detectors.")
    assert resp.status_code == 200
    assert "Fire-safety report" in resp.text
    assert "Lease PDF read" not in resp.text


def test_nothing_submitted_asks_for_input(client):
    resp = client.post("/check", data={"listing": ""}, headers=HX)
    assert "or upload a lease PDF" in resp.text


def test_very_large_request_rejected_before_reading(client):
    resp = upload(client, b"%PDF-" + b"0" * (MAX_REQUEST_BYTES + 1024))
    assert resp.status_code == 413


def test_uploads_up_to_limit_stay_in_memory(client, monkeypatch):
    # Starlette spools large uploads to a temp file ("rollover"); our setting keeps
    # PDFs up to the limit in memory. Fail if anything rolls over to disk.
    import tempfile

    rolled_over = []
    original = tempfile.SpooledTemporaryFile.rollover

    def spy(self):
        rolled_over.append(True)
        return original(self)

    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "rollover", spy)
    padded = pdfs.text_pdf(pdfs.LEASE_LINES) + b"\n%" + b"0" * (4 * 1024 * 1024)  # ~4 MB
    resp = upload(client, padded)
    assert resp.status_code == 200
    assert "Fire-safety report" in resp.text
    assert rolled_over == []
