"""End-to-end API tests driving the real ASGI app via Starlette's TestClient.

These reset the in-memory ledger between tests so metering assertions are
deterministic, and use the synthetic acmebank fixture as the uploaded PDF.
"""

import base64
import io

import pytest
from fastapi.testclient import TestClient

import statement_to_excel.api as api_mod
from statement_to_excel.billing import Ledger, MockBillingProvider


@pytest.fixture
def client(monkeypatch):
    # Fresh ledger + provider per test.
    monkeypatch.setattr(api_mod, "LEDGER", Ledger())
    monkeypatch.setattr(api_mod, "PROVIDER", MockBillingProvider())
    return TestClient(api_mod.app)


@pytest.fixture
def pdf_bytes(fixtures_dir):
    return (fixtures_dir / "acmebank.pdf").read_bytes()


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["billing"] == "mock"


def test_pricing_catalog(client):
    r = client.get("/api/pricing")
    assert r.status_code == 200
    body = r.json()
    ids = {p["id"] for p in body["plans"]}
    assert {"free", "starter", "business", "firm"} <= ids
    assert any(p["id"] == "pack_50" for p in body["credit_packs"])


def test_account_defaults(client):
    r = client.get("/api/account/newbie")
    assert r.status_code == 200
    assert r.json()["plan"] == "free"
    assert r.json()["credits"] == 0
    assert r.json()["included_remaining"] == 3


def test_quote_endpoint(client):
    r = client.post("/api/account/q1/quote", json={"pages": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["from_included"] == 3
    assert body["from_credits"] == 2
    assert body["sufficient"] is False


def test_convert_xlsx_charges_one_page(client, pdf_bytes):
    files = {"file": ("acmebank.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    r = client.post(
        "/api/convert", files=files, data={"account_id": "c1", "fmt": "xlsx"}
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert int(r.headers["x-transaction-count"]) == 5
    # 1-page statement charged against the free included allowance.
    acct = client.get("/api/account/c1").json()
    assert acct["pages_used_this_cycle"] == 1
    assert acct["included_remaining"] == 2


def test_convert_json_inline(client, pdf_bytes):
    files = {"file": ("acmebank.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    r = client.post(
        "/api/convert", files=files, data={"account_id": "c2", "fmt": "json"}
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["transactions"]) == 5
    assert body["summary"]["count"] == 5
    assert body["charge"]["pages"] == 1


def test_convert_csv(client, pdf_bytes):
    files = {"file": ("acmebank.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    r = client.post(
        "/api/convert", files=files, data={"account_id": "c3", "fmt": "csv"}
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "PAYROLL" in r.text or "DEPOSIT" in r.text


def test_convert_rejects_bad_format(client, pdf_bytes):
    files = {"file": ("acmebank.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    r = client.post(
        "/api/convert", files=files, data={"account_id": "c4", "fmt": "pdf"}
    )
    assert r.status_code == 400


def test_convert_empty_upload(client):
    files = {"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")}
    r = client.post("/api/convert", files=files, data={"account_id": "c5"})
    assert r.status_code == 400


def test_convert_unparseable_pdf_422(client, fixtures_dir):
    data = (fixtures_dir / "scanned_empty.pdf").read_bytes()
    files = {"file": ("scan.pdf", io.BytesIO(data), "application/pdf")}
    r = client.post(
        "/api/convert", files=files, data={"account_id": "c6", "fmt": "csv"}
    )
    assert r.status_code == 422


def test_convert_blocks_when_out_of_allowance(client, pdf_bytes):
    # Exhaust the free allowance (3 pages) with 3 single-page conversions.
    for _ in range(3):
        files = {"file": ("a.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
        ok = client.post(
            "/api/convert", files=files, data={"account_id": "broke", "fmt": "csv"}
        )
        assert ok.status_code == 200
    # 4th conversion has no allowance and no credits -> 402.
    files = {"file": ("a.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    r = client.post(
        "/api/convert", files=files, data={"account_id": "broke", "fmt": "csv"}
    )
    assert r.status_code == 402
    assert r.json()["error"] == "insufficient_credits"


def test_checkout_then_fulfill_grants_credits(client):
    r = client.post("/api/checkout", json={"account_id": "payer", "sku": "pack_50"})
    assert r.status_code == 200
    sid = r.json()["session_id"]
    f = client.post(f"/api/checkout/{sid}/fulfill")
    assert f.status_code == 200
    acct = client.get("/api/account/payer").json()
    assert acct["credits"] == 50


def test_checkout_then_fulfill_plan_reports_the_right_account(client):
    # Seed an unrelated ledger entry first, so an implementation that guesses
    # the account from the global charge log returns the wrong one.
    other_sid = client.post(
        "/api/checkout", json={"account_id": "other", "sku": "pack_50"}
    ).json()["session_id"]
    client.post(f"/api/checkout/{other_sid}/fulfill")

    r = client.post("/api/checkout", json={"account_id": "upgrader", "sku": "business"})
    assert r.status_code == 200
    sid = r.json()["session_id"]
    f = client.post(f"/api/checkout/{sid}/fulfill")
    assert f.status_code == 200
    acct = f.json()["account"]
    assert acct is not None
    assert acct["id"] == "upgrader"
    assert acct["plan"] == "business"
    # The grant is visible on the account resource too.
    assert client.get("/api/account/upgrader").json()["plan"] == "business"


def test_fulfill_unknown_session_404(client):
    r = client.post("/api/checkout/cs_mock_does_not_exist/fulfill")
    assert r.status_code == 404


def test_buying_credits_unblocks_conversion(client, pdf_bytes):
    # Drain allowance.
    for _ in range(3):
        files = {"file": ("a.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
        client.post(
            "/api/convert", files=files, data={"account_id": "vip", "fmt": "csv"}
        )
    # Buy credits.
    sid = client.post(
        "/api/checkout", json={"account_id": "vip", "sku": "pack_50"}
    ).json()["session_id"]
    client.post(f"/api/checkout/{sid}/fulfill")
    # Now conversion succeeds and spends a credit.
    files = {"file": ("a.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    r = client.post(
        "/api/convert", files=files, data={"account_id": "vip", "fmt": "csv"}
    )
    assert r.status_code == 200
    assert int(r.headers["x-credits-remaining"]) == 49


def test_convert_preview_charges_once_and_inlines_the_file(client, pdf_bytes):
    # One call serves both the UI preview table and the download -> one charge.
    files = {"file": ("acmebank.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    r = client.post(
        "/api/convert",
        files=files,
        data={"account_id": "pv", "fmt": "xlsx", "preview": "1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["transactions"]) == 5
    assert body["summary"]["count"] == 5
    assert body["charge"]["pages"] == 1
    assert body["filename"] == "statement.xlsx"
    assert body["media_type"].startswith("application/vnd.openxmlformats")
    blob = base64.b64decode(body["file_b64"])
    assert blob[:2] == b"PK"  # zip container == real xlsx bytes
    # Exactly ONE page charged for the combined preview+download call.
    acct = client.get("/api/account/pv").json()
    assert acct["pages_used_this_cycle"] == 1
    assert acct["included_remaining"] == 2
