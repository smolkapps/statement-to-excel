"""Regression: a retried purchase must reuse the original checkout session."""

from fastapi.testclient import TestClient

import statement_to_excel.api as api
from statement_to_excel.billing import PersistentLedger


def test_duplicate_checkout_request_creates_one_payment_intent(monkeypatch, tmp_path, configured_provider):
    from tests.test_billing_stripe import PaymentDouble
    provider = PaymentDouble()
    monkeypatch.setattr(api, "PROVIDER", provider)
    monkeypatch.setattr(api, "LEDGER", PersistentLedger(str(tmp_path / "billing.sqlite3")))
    with TestClient(api.app) as client:
        headers = {"Idempotency-Key": "regression-purchase-0000000000000001"}
        body = {"account_id": "regression-buyer", "sku": "pack_50"}
        first = client.post("/api/checkout", json=body, headers=headers)
        duplicate = client.post("/api/checkout", json=body, headers=headers)
    assert first.status_code == duplicate.status_code == 200
    assert first.json()["session_id"] == duplicate.json()["session_id"]
    assert len(provider.calls) == 1
