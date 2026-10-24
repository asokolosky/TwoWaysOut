"""Build small PDFs in memory for tests (no extra dependencies)."""

import io

from pypdf import PdfWriter


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_pdf(lines: list[str]) -> bytes:
    """A one-page PDF with real, extractable text."""
    ops = ["BT", "/F1 11 Tf", "72 720 Td", "14 TL"]
    for line in lines:
        ops.append(f"({_escape(line)}) Tj T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref))
    return out.getvalue()


def blank_pdf(pages: int = 1) -> bytes:
    """Pages with no text, like a scanned lease."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def encrypted_pdf(password: str) -> bytes:
    writer = PdfWriter(clone_from=io.BytesIO(text_pdf(LEASE_LINES)))
    writer.encrypt(user_password=password, owner_password="owner")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


LEASE_LINES = [
    "RESIDENTIAL LEASE AGREEMENT",
    "Premises: 182 Example Street, Unit 2, Amherst, MA 01002.",
    "The Premises include four bedrooms, one of which is located in the basement.",
    "Tenant shall not remove or disable any smoke detector.",
    "Heat is provided by a gas boiler. Tenant may use space heaters in the basement bedroom.",
]
