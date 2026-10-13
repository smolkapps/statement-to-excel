"""Synthetic provider doubles, real Stripe signatures, durable payment safety."""
import hashlib
import hmac
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import statement_to_excel.api as api
from statement_to_excel.billing import (
    BillingError, PersistentLedger, StripeBillingProvider,
    apply_webhook, create_checkout,
)


class PaymentDouble:
    name = "stripe"
    mode = "test"

    def __init__(self):
        self.sessions = {}
        self.calls = []
        self.fail_after_creation = False
        self.lock = threading.Lock()

    def create_checkout(self, account_id, sku, idempotency_key):
        with self.lock:
            self.calls.append(idempotency_key)
            if idempotency_key not in self.sessions:
                self.sessions[idempotency_key] = {
                    "session_id": "cs_test_" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:24],
                    "checkout_url": "https://checkout.stripe.com/synthetic-test-only",
                    "provider": "stripe", "mode": "test",
                }
            if self.fail_after_creation:
                self.fail_after_creation = False
                raise BillingError("Synthetic ambiguous provider timeout.")
            return dict(self.sessions[idempotency_key])


@pytest.fixture
def ledger(tmp_path):
    return PersistentLedger(str(tmp_path / "billing.sqlite3"))


@pytest.fixture
def provider():
    return PaymentDouble()


def buy(ledger, provider, sku="pack_50", key="purchase-request-000000001", account="buyer"):
    return create_checkout(ledger, provider, account, sku, key)


def paid_event(session_id, sku="pack_50", event_id="evt_synthetic_001", account="buyer"):
    from statement_to_excel.billing import CREDIT_PACKS, PLANS
    is_pack = sku in CREDIT_PACKS
    amount = CREDIT_PACKS[sku].price_usd if is_pack else PLANS[sku].monthly_price_usd
    return {"id": event_id, "type": "checkout.session.completed", "livemode": False,
            "data": {"object": {
                "id": session_id, "livemode": False, "payment_status": "paid",
                "currency": "usd", "amount_total": int(amount * 100),
                "mode": "payment" if is_pack else "subscription",
                "subscription": None if is_pack else "sub_synthetic_001",
                "metadata": {"account_id": account, "sku": sku},
            }}}


def sign(payload, secret="whsec_synthetic_not_a_credential", timestamp=None):
    stamp = int(time.time()) if timestamp is None else timestamp
    signature = hmac.new(secret.encode(), str(stamp).encode() + b"." + payload, hashlib.sha256).hexdigest()
    return f"t={stamp},v1={signature}"


def test_retries_and_accidental_new_keys_reuse_one_session_across_restart(ledger, provider):
    first = buy(ledger, provider)
    assert buy(ledger, provider) == first
    restarted = PersistentLedger(ledger.database_path)
    assert buy(restarted, provider, key="accidental-second-key-0002") == first
    assert buy(restarted, provider, key="accidental-second-key-0002") == first
    assert len(provider.calls) == len(provider.sessions) == 1
    assert not restarted.get_or_create("buyer").pro


def test_simultaneous_duplicates_have_one_provider_call(ledger, provider):
    def invoke(_):
        return buy(PersistentLedger(ledger.database_path), provider)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(invoke, range(12)))
    assert len({r["session_id"] for r in results}) == 1
    assert len(provider.calls) == len(provider.sessions) == 1


def test_pending_cross_plan_race_and_restart_cannot_create_two_subscriptions(ledger, provider):
    def invoke(sku):
        try:
            return buy(PersistentLedger(ledger.database_path), provider, sku, key="plan-request-0000000-" + sku)
        except BillingError as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(invoke, ["starter", "business"]))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert results.count(409) == 1
    assert len(provider.sessions) == 1
    first_sku = "starter" if isinstance(results[0], dict) else "business"
    second_sku = "business" if first_sku == "starter" else "starter"
    with pytest.raises(BillingError, match="Another plan"):
        buy(PersistentLedger(ledger.database_path), provider, second_sku, key="new-plan-request-0000003")
    assert len(provider.sessions) == 1


def test_ambiguous_failure_retry_uses_original_stripe_key_after_restart(ledger, provider):
    provider.fail_after_creation = True
    with pytest.raises(BillingError):
        buy(ledger, provider)
    account = ledger.get_or_create("buyer")
    assert not account.pro and account.credits == 0
    session = buy(PersistentLedger(ledger.database_path), provider)
    assert len(provider.sessions) == 1
    assert provider.calls[0] == provider.calls[1]
    assert session["session_id"]


def test_ambiguous_request_older_than_stripe_retention_fails_closed(ledger, provider):
    provider.fail_after_creation = True
    with pytest.raises(BillingError):
        buy(ledger, provider)
    with ledger.transaction() as db:
        db.execute("UPDATE checkout_requests SET attempted_at=?", (time.time() - 24 * 3600,))
    with pytest.raises(BillingError, match="reconciliation"):
        buy(PersistentLedger(ledger.database_path), provider)
    assert len(provider.calls) == len(provider.sessions) == 1
    assert not ledger.get_or_create("buyer").pro


def test_reusing_request_key_for_other_purchase_is_conflict(ledger, provider):
    buy(ledger, provider)
    for account, sku in [("other", "pack_50"), ("buyer", "pack_200")]:
        with pytest.raises(BillingError) as error:
            buy(ledger, provider, sku, account=account)
        assert error.value.status_code == 409
    assert len(provider.sessions) == 1


def test_paid_webhook_grants_pro_and_credits_once_concurrent_across_restart(ledger, provider):
    session = buy(ledger, provider)
    def deliver(i):
        event = paid_event(session["session_id"], event_id=f"evt_duplicate_{i}")
        return apply_webhook(PersistentLedger(ledger.database_path), event)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(deliver, range(12)))
    assert sum(r["granted"] for r in results) == 1
    acct = PersistentLedger(ledger.database_path).get_or_create("buyer")
    assert acct.pro and acct.credits == 50
    assert not apply_webhook(ledger, paid_event(session["session_id"], event_id="evt_duplicate_0"))["granted"]
    with ledger.transaction() as db:
        assert db.execute("SELECT count(*) FROM entitlements").fetchone()[0] == 1


def test_entitlement_and_grant_rollback_together_on_database_failure(ledger, provider):
    session = buy(ledger, provider)
    with ledger.transaction() as db:
        db.execute("CREATE TRIGGER fail_grant BEFORE UPDATE ON accounts BEGIN SELECT RAISE(ABORT, 'synthetic outage'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError, match="synthetic outage"):
        apply_webhook(ledger, paid_event(session["session_id"]))
    with ledger.transaction() as db:
        assert db.execute("SELECT count(*) FROM entitlements").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM webhook_events").fetchone()[0] == 0
        db.execute("DROP TRIGGER fail_grant")
    assert apply_webhook(ledger, paid_event(session["session_id"]))["granted"]
    assert ledger.get_or_create("buyer").credits == 50


@pytest.mark.parametrize("field,value", [("payment_status", "unpaid"), ("livemode", True)])
def test_unpaid_or_live_sessions_cannot_grant(ledger, provider, field, value):
    session = buy(ledger, provider)
    event = paid_event(session["session_id"])
    event["data"]["object"][field] = value
    assert not apply_webhook(ledger, event)["granted"]
    assert not ledger.get_or_create("buyer").pro


@pytest.mark.parametrize("mutation", ["amount", "currency", "metadata", "mode", "live_event"])
def test_mismatched_paid_events_cannot_grant(ledger, provider, mutation):
    event = paid_event(buy(ledger, provider)["session_id"])
    obj = event["data"]["object"]
    if mutation == "amount": obj["amount_total"] = 1
    if mutation == "currency": obj["currency"] = "eur"
    if mutation == "metadata": obj["metadata"]["account_id"] = "attacker"
    if mutation == "mode": obj["mode"] = "subscription"
    if mutation == "live_event": event["livemode"] = True
    with pytest.raises(BillingError):
        apply_webhook(ledger, event)
    assert not ledger.get_or_create("buyer").pro


def test_real_sdk_signed_webhook_only_can_grant_via_api(ledger, provider, monkeypatch):
    sid = buy(ledger, provider)["session_id"]
    stripe_provider = StripeBillingProvider("sk_test_synthetic_not_a_credential", "whsec_synthetic_not_a_credential")
    monkeypatch.setattr(api, "LEDGER", ledger)
    monkeypatch.setattr(api, "PROVIDER", stripe_provider)
    payload = json.dumps(paid_event(sid)).encode()
    with TestClient(api.app) as client:
        assert client.post(f"/api/checkout/{sid}/fulfill").status_code == 404
        assert client.post("/api/stripe/webhook", content=payload).status_code == 400
        assert client.post("/api/stripe/webhook", content=payload, headers={"Stripe-Signature": sign(payload, timestamp=int(time.time()) - 600)}).status_code == 400
        assert not ledger.get_or_create("buyer").pro
        headers = {"Stripe-Signature": sign(payload)}
        assert client.post("/api/stripe/webhook", content=payload, headers=headers).json()["granted"]
        assert not client.post("/api/stripe/webhook", content=payload, headers=headers).json()["granted"]
    assert ledger.get_or_create("buyer").credits == 50


def test_subscription_purchase_unlocks_once_and_cannot_be_bought_again(ledger, provider):
    session = buy(ledger, provider, "business")
    event = paid_event(session["session_id"], "business")
    assert apply_webhook(ledger, event)["granted"]
    event["id"] = "evt_other_delivery_same_session"
    assert not apply_webhook(PersistentLedger(ledger.database_path), event)["granted"]
    acct = ledger.get_or_create("buyer")
    assert acct.pro and acct.plan_id == "business"
    with pytest.raises(BillingError, match="already active"):
        buy(ledger, provider, "firm", key="another-plan-purchase-00002")
    assert len(provider.sessions) == 1


def test_subscription_expiry_preserves_pro_from_credit_pack_purchase(ledger, provider):
    pack = buy(ledger, provider)
    apply_webhook(ledger, paid_event(pack["session_id"]))
    plan = buy(ledger, provider, "starter", key="plan-request-synthetic-0002")
    apply_webhook(ledger, paid_event(plan["session_id"], "starter", event_id="evt_plan"))
    event = {"id": "evt_cancel", "type": "customer.subscription.deleted", "livemode": False,
             "data": {"object": {"id": "sub_synthetic_001"}}}
    apply_webhook(ledger, event)
    acct = ledger.get_or_create("buyer")
    assert acct.plan_id == "free" and acct.pro and acct.credits == 50


def test_expired_pending_checkout_allows_new_purchase(ledger, provider):
    session = buy(ledger, provider, "starter")
    event = {"id": "evt_expired", "type": "checkout.session.expired", "livemode": False,
             "data": {"object": {"id": session["session_id"]}}}
    apply_webhook(ledger, event)
    buy(ledger, provider, "business", key="new-purchase-after-expiry-0001")
    assert len(provider.sessions) == 2
    assert not ledger.get_or_create("buyer").pro


def test_subscription_invoice_cycles_reset_allowance_only_once(ledger, provider):
    session = buy(ledger, provider, "starter")
    apply_webhook(ledger, paid_event(session["session_id"], "starter"))
    ledger.charge_pages("buyer", 10)
    event = {"id": "evt_invoice", "type": "invoice.paid", "livemode": False,
             "data": {"object": {"subscription": "sub_synthetic_001", "period_start": 100, "billing_reason": "subscription_cycle"}}}
    apply_webhook(ledger, event)
    assert ledger.get_or_create("buyer").pages_used_this_cycle == 0
    ledger.charge_pages("buyer", 2)
    event["id"] = "evt_same_period_other_event"
    apply_webhook(ledger, event)
    assert ledger.get_or_create("buyer").pages_used_this_cycle == 2


def test_sdk_checkout_receives_test_key_server_price_and_provider_idempotency(monkeypatch):
    import stripe
    recorded = {}
    def fake_create(**kwargs):
        recorded.update(kwargs)
        return {"id": "cs_test_sdk", "url": "https://checkout.stripe.com/test"}
    monkeypatch.setattr(stripe.checkout.Session, "create", fake_create)
    provider = StripeBillingProvider("sk_test_synthetic_not_a_credential", "whsec_synthetic_not_a_credential", "https://example.test")
    result = provider.create_checkout("buyer", "business", "stx-stable-key")
    assert result["mode"] == "test"
    assert recorded["api_key"].startswith("sk_test_")
    assert recorded["idempotency_key"] == "stx-stable-key"
    assert recorded["mode"] == "subscription"
    price = recorded["line_items"][0]["price_data"]
    assert price["unit_amount"] == 7900 and price["recurring"]["interval"] == "month"
    assert recorded["success_url"].startswith("https://example.test/?checkout=success")


def test_checkout_missing_credentials_and_live_keys_fail_closed(ledger, monkeypatch):
    monkeypatch.delenv("STX_STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STX_STRIPE_WEBHOOK_SECRET", raising=False)
    provider = StripeBillingProvider()
    with pytest.raises(BillingError, match="test credentials"):
        buy(ledger, provider)
    with pytest.raises(RuntimeError, match="Michael"):
        StripeBillingProvider(secret_key="sk_" + "live_synthetic_forbidden")
    assert not ledger.get_or_create("buyer").pro
    with ledger.transaction() as db:
        assert db.execute("SELECT count(*) FROM checkout_requests").fetchone()[0] == 0


def test_persistent_conversion_retry_charges_one_time_with_concurrent_restart(ledger):
    def charge(_):
        return PersistentLedger(ledger.database_path).charge_pages_once("buyer", 2, "conversion-key", "opaque-fingerprint")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(charge, range(12)))
    assert all(r == results[0] for r in results)
    assert PersistentLedger(ledger.database_path).get_or_create("buyer").pages_used_this_cycle == 2
    with pytest.raises(ValueError):
        ledger.charge_pages_once("buyer", 2, "conversion-key", "different")


def test_deleted_subscription_before_completed_never_revives_pro(ledger, provider):
    session = buy(ledger, provider, "starter")
    deleted = {"id": "evt_deleted_early", "type": "customer.subscription.deleted", "livemode": False,
               "data": {"object": {"id": "sub_synthetic_001"}}}
    apply_webhook(ledger, deleted)
    completed = paid_event(session["session_id"], "starter")
    assert not apply_webhook(PersistentLedger(ledger.database_path), completed)["granted"]
    assert not ledger.get_or_create("buyer").pro
    with ledger.transaction() as db:
        assert db.execute("SELECT state FROM checkout_requests").fetchone()[0] == "cancelled"
        assert db.execute("SELECT count(*) FROM entitlements").fetchone()[0] == 0


def test_early_invoice_cycle_prevents_delayed_old_invoice_reset(ledger, provider):
    session = buy(ledger, provider, "starter")
    early = {"id": "evt_invoice_early", "type": "invoice.paid", "livemode": False,
             "data": {"object": {"subscription": "sub_synthetic_001", "period_start": 200, "billing_reason": "subscription_cycle"}}}
    apply_webhook(ledger, early)
    apply_webhook(ledger, paid_event(session["session_id"], "starter"))
    ledger.charge_pages("buyer", 10)
    early["id"] = "evt_invoice_old_delayed"
    early["data"]["object"]["period_start"] = 100
    apply_webhook(ledger, early)
    assert ledger.get_or_create("buyer").pages_used_this_cycle == 10


def test_signed_webhook_recovers_creation_crash_without_browser_retry(ledger, provider):
    provider.fail_after_creation = True
    with pytest.raises(BillingError):
        buy(ledger, provider)
    response = next(iter(provider.sessions.values()))
    event = paid_event(response["session_id"])
    event["data"]["object"]["metadata"]["purchase_key"] = provider.calls[0]
    assert apply_webhook(PersistentLedger(ledger.database_path), event)["granted"]
    assert ledger.get_or_create("buyer").credits == 50
    assert len(provider.sessions) == 1
    with pytest.raises(BillingError, match="already completed"):
        buy(ledger, provider)
    assert len(provider.calls) == 1


def test_recovery_rejects_different_session_and_wrong_amount(ledger, provider):
    original = buy(ledger, provider)
    conflicting = paid_event("cs_test_different_session")
    conflicting["data"]["object"]["metadata"]["purchase_key"] = provider.calls[0]
    with pytest.raises(BillingError, match="conflicts"):
        apply_webhook(ledger, conflicting)
    with ledger.transaction() as db:
        assert db.execute("SELECT session_id FROM checkout_requests").fetchone()[0] == original["session_id"]
    provider.fail_after_creation = True
    with pytest.raises(BillingError):
        buy(ledger, provider, key="second-purchase-ambiguous-001", account="other")
    missing = provider.sessions[provider.calls[-1]]
    wrong = paid_event(missing["session_id"], account="other", event_id="evt_wrong")
    wrong["data"]["object"]["metadata"]["purchase_key"] = provider.calls[-1]
    wrong["data"]["object"]["amount_total"] = 1
    with pytest.raises(BillingError, match="amount"):
        apply_webhook(ledger, wrong)
    with ledger.transaction() as db:
        assert db.execute("SELECT session_id FROM checkout_requests WHERE account_id='other'").fetchone()[0] is None
    wrong["data"]["object"]["amount_total"] = 3000
    assert apply_webhook(ledger, wrong)["granted"]


def test_expired_webhook_recovers_ambiguous_creation_and_unblocks_plan(ledger, provider):
    provider.fail_after_creation = True
    with pytest.raises(BillingError):
        buy(ledger, provider, "starter")
    session = next(iter(provider.sessions.values()))
    event = {"id": "evt_unknown_expired", "type": "checkout.session.expired", "livemode": False,
             "data": {"object": {"id": session["session_id"], "metadata": {
                 "purchase_key": provider.calls[0], "account_id": "buyer", "sku": "starter"}}}}
    apply_webhook(ledger, event)
    buy(ledger, provider, "business", key="new-plan-after-verified-expiry")
    assert len(provider.sessions) == 2
    assert not ledger.get_or_create("buyer").pro


def test_status_is_account_bound_and_verified_before_returning_paid(ledger, provider, monkeypatch):
    sid = buy(ledger, provider)["session_id"]
    monkeypatch.setattr(api, "LEDGER", ledger)
    with TestClient(api.app) as client:
        assert client.get(f"/api/checkout/{sid}", params={"account_id": "other"}).status_code == 404
        pending = client.get(f"/api/checkout/{sid}", params={"account_id": "buyer"}).json()
        assert pending == {"status": "pending", "sku": "pack_50", "session_id": sid}
        apply_webhook(ledger, paid_event(sid))
        assert client.get(f"/api/checkout/{sid}", params={"account_id": "buyer"}).json()["status"] == "fulfilled"
        # Intentional new pack purchase is allowed only with a fresh key.
        again = buy(ledger, provider, key="intentional-repeat-pack-purchase")
        assert again["session_id"] != sid
        assert len(provider.sessions) == 2
