"""Bad or unsupported PDFs fail visibly without consuming an allowance."""

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.lib.utils import ImageReader

import statement_to_excel.api as api
from statement_to_excel.billing import Ledger
from tests.accuracy_harness import LAYOUTS, measure, render
from tests.test_pdf_edges import _pdf, _text_page


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "LEDGER", Ledger())
    return TestClient(api.app)


def _failure_pdf(kind):
    if kind == "encrypted":
        return _pdf(_text_page, encrypt=StandardEncryption("synthetic-fixture-password"))
    if kind == "invalid":
        return BytesIO(b"invalid PDF")
    def draw(c):
        if kind == "multiple accounts":
            _text_page(c, account="xxxx1111")
            c.showPage()
            _text_page(c, account="xxxx2222")
            return
        if kind.startswith("mixed") or kind == "header scan":
            _text_page(c)
            c.showPage()
        if kind == "header scan":
            c.drawString(40, 750, "Synthetic statement - January 2024")
            c.drawString(40, 730, "Account ending 0000")
        c.drawImage(ImageReader(Image.new("RGB", (100, 100), "white")), 40, 400, 500, 300)
    return _pdf(draw)


@pytest.mark.parametrize(("kind", "message"), [
    ("encrypted", "Password-protected PDF"),
    ("invalid", "Invalid or damaged PDF"),
    ("scanned", "scanned/image-only"),
    ("mixed scan", "mixed scanned/text PDFs"),
    ("header scan", "scanned body beneath selectable headers"),
    ("multiple accounts", "Multiple accounts detected"),
])
def test_pdf_edge_returns_clear_422_and_never_charges(client, kind, message):
    before = client.get("/api/account/synthetic-edge").json()
    response = client.post("/api/convert", files={
        "file": ("synthetic-edge.pdf", _failure_pdf(kind), "application/pdf"),
    }, data={"account_id": "synthetic-edge", "fmt": "json"})
    assert response.status_code == 422, response.text
    assert message in response.json()["detail"]
    assert client.get("/api/account/synthetic-edge").json() == before


@pytest.mark.parametrize("slug", ["wells-fargo", "us-bank", "pnc"])
def test_multi_page_api_preserves_exact_rows_and_charges_each_page_once(client, tmp_path, slug):
    layout = next(layout for layout in LAYOUTS if layout.slug == slug)
    path, expected = render(layout, tmp_path)
    response = client.post("/api/convert", files={
        "file": (path.name, BytesIO(path.read_bytes()), "application/pdf"),
    }, data={"account_id": "synthetic-pages", "fmt": "json"},
       headers={"Idempotency-Key": f"synthetic-multi-page-{slug}"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert measure(expected, body["transactions"])["accuracy"] == 1
    assert body["charge"]["pages"] == 2
    assert client.get("/api/account/synthetic-pages").json()["pages_used_this_cycle"] == 2
