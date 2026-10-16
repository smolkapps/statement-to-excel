"""Retries regenerate output in memory, but must never debit the same operation twice."""
import pytest
from fastapi.testclient import TestClient

import statement_to_excel.api as api
from statement_to_excel.conversion_timeout import ConversionWorkerError
from statement_to_excel.billing import Ledger


@pytest.fixture
def client(monkeypatch, configured_provider):
    monkeypatch.setattr(api, "LEDGER", Ledger())
    return TestClient(api.app)


@pytest.mark.parametrize("fmt", ["xlsx", "csv", "json"])
def test_duplicate_conversion_debits_once(client, fixtures_dir, fmt):
    data = (fixtures_dir / "acmebank.pdf").read_bytes()
    responses = [client.post("/api/convert", files={"file": ("synthetic.pdf", data, "application/pdf")}, data={"account_id": "retry", "fmt": fmt}, headers={"Idempotency-Key": "conversion-operation-123456"}) for _ in range(2)]
    assert all(response.status_code == 200 for response in responses)
    if fmt == "xlsx":
        import io
        from openpyxl import load_workbook
        rows = [list(load_workbook(io.BytesIO(response.content))["Transactions"].values) for response in responses]
        assert rows[0] == rows[1]
    else:
        assert responses[0].content == responses[1].content
    assert client.get("/api/account/retry").json()["pages_used_this_cycle"] == 1


def test_writer_failure_never_debits(client, fixtures_dir, monkeypatch):
    async def fail(*args):
        raise ConversionWorkerError()
    monkeypatch.setattr(api, "run_conversion", fail)
    response = client.post("/api/convert", files={"file": ("synthetic.pdf", (fixtures_dir / "acmebank.pdf").read_bytes(), "application/pdf")}, data={"account_id": "writer", "fmt": "xlsx"}, headers={"Idempotency-Key": "conversion-writer-123456"})
    assert response.status_code == 500
    assert client.get("/api/account/writer").json()["pages_used_this_cycle"] == 0


def test_conversion_key_cannot_be_reused_for_different_input(client, fixtures_dir):
    kwargs = dict(files={"file": ("synthetic.pdf", (fixtures_dir / "acmebank.pdf").read_bytes(), "application/pdf")}, headers={"Idempotency-Key": "conversion-conflict-123456"})
    assert client.post("/api/convert", data={"account_id": "conflict", "fmt": "csv", "currency": "USD"}, **kwargs).status_code == 200
    assert client.post("/api/convert", data={"account_id": "conflict", "fmt": "csv", "currency": "EUR"}, **kwargs).status_code == 409
    assert client.get("/api/account/conflict").json()["pages_used_this_cycle"] == 1


def test_retry_after_allowance_exhausted_still_returns_original_charge(client, fixtures_dir):
    data = (fixtures_dir / "acmebank.pdf").read_bytes()
    def request(key):
        return client.post("/api/convert", files={"file": ("synthetic.pdf", data, "application/pdf")}, data={"account_id": "exhausted", "fmt": "csv"}, headers={"Idempotency-Key": key})
    first = request("exhausted-operation-0001")
    assert first.status_code == 200
    assert request("exhausted-operation-0002").status_code == 200
    assert request("exhausted-operation-0003").status_code == 200
    retry = request("exhausted-operation-0001")
    assert retry.status_code == 200
    assert retry.content == first.content
    assert client.get("/api/account/exhausted").json()["pages_used_this_cycle"] == 3


def test_concurrent_conversion_metering_survives_restart(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from statement_to_excel.billing import PersistentLedger
    path = str(tmp_path / "billing.sqlite3")
    def debit(_):
        return PersistentLedger(path).charge_pages_once("concurrent", 1, "concurrent-conversion-operation", "synthetic-fingerprint")
    # Initialize schema before concurrent connections contend on the charge.
    PersistentLedger(path)
    with ThreadPoolExecutor(max_workers=8) as executor:
        charges = list(executor.map(debit, range(16)))
    restarted = PersistentLedger(path)
    assert all(charge == charges[0] for charge in charges)
    assert restarted.get_or_create("concurrent").pages_used_this_cycle == 1
    assert restarted.charge_pages_once("concurrent", 1, "concurrent-conversion-operation", "synthetic-fingerprint") == charges[0]
    with restarted.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM conversion_charges").fetchone()[0] == 1
