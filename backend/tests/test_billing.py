from decimal import Decimal

import pytest

from statement_to_excel.billing import (
    CREDIT_PACKS,
    InsufficientCredits,
    Ledger,
    MockBillingProvider,
    PLANS,
    get_provider,
)


def test_per_credit_pricing_is_business_tier():
    # Sanity: packs are priced at business rates ($30-$100+), not pennies.
    pack = CREDIT_PACKS["pack_50"]
    assert pack.price_usd == Decimal("30")
    assert pack.per_credit_usd == Decimal("0.6000")
    # Larger packs are cheaper per credit (volume discount).
    assert CREDIT_PACKS["pack_1000"].per_credit_usd < pack.per_credit_usd


def test_free_plan_included_then_blocks():
    led = Ledger()
    acct = led.get_or_create("u1")
    assert acct.included_remaining() == PLANS["free"].included_pages == 3
    # Spend the 3 included pages.
    led.charge_pages("u1", 3)
    assert acct.included_remaining() == 0
    assert not acct.can_process(1)
    with pytest.raises(InsufficientCredits):
        led.charge_pages("u1", 1)


def test_credits_cover_overage():
    led = Ledger()
    led.add_credits("u2", 5)
    acct = led.get_or_create("u2")
    # 3 included + 5 credits = 8 pages possible.
    assert acct.can_process(8)
    assert not acct.can_process(9)
    charge = led.charge_pages("u2", 8)
    assert charge["from_included"] == 3
    assert charge["from_credits"] == 5
    assert acct.credits == 0


def test_charge_is_atomic_on_failure():
    led = Ledger()
    led.add_credits("u3", 1)
    acct = led.get_or_create("u3")
    before = (acct.credits, acct.pages_used_this_cycle)
    with pytest.raises(InsufficientCredits):
        led.charge_pages("u3", 10)  # needs 7 credits, has 1
    assert (acct.credits, acct.pages_used_this_cycle) == before


def test_quote_does_not_mutate():
    led = Ledger()
    led.add_credits("u4", 2)
    acct = led.get_or_create("u4")
    q = acct.quote(4)
    assert q == {
        "pages": 4,
        "from_included": 3,
        "from_credits": 1,
        "credits_after": 1,
        "sufficient": True,
    }
    # nothing changed
    assert acct.credits == 2
    assert acct.pages_used_this_cycle == 0


def test_reset_cycle_restores_allowance():
    led = Ledger()
    led.charge_pages("u5", 3)
    assert led.get_or_create("u5").included_remaining() == 0
    led.reset_cycle("u5")
    assert led.get_or_create("u5").included_remaining() == 3


def test_plan_upgrade_grants_more_included():
    led = Ledger()
    led.set_plan("u6", "business")
    acct = led.get_or_create("u6")
    assert acct.plan_id == "business"
    assert acct.included_remaining() == 500


def test_set_unknown_plan_raises():
    led = Ledger()
    with pytest.raises(KeyError):
        led.set_plan("u7", "platinum-unobtainium")


def test_mock_provider_buy_credits_flow():
    led = Ledger()
    prov = MockBillingProvider()
    session = prov.create_checkout("buyer", "pack_200")
    assert session["checkout_url"].startswith("https://mock.local/checkout/")
    acct = prov.fulfill(led, session["session_id"])
    assert acct.credits == 200
    # Fulfilling twice is rejected (idempotency guard).
    with pytest.raises(KeyError):
        prov.fulfill(led, session["session_id"])


def test_mock_provider_buy_plan_flow():
    led = Ledger()
    prov = MockBillingProvider()
    session = prov.create_checkout("buyer", "firm")
    prov.fulfill(led, session["session_id"])
    assert led.get_or_create("buyer").plan_id == "firm"


def test_mock_provider_unknown_sku():
    prov = MockBillingProvider()
    with pytest.raises(KeyError):
        prov.create_checkout("buyer", "not_a_sku")


def test_get_provider_default_is_mock(monkeypatch):
    monkeypatch.delenv("STX_BILLING_PROVIDER", raising=False)
    assert get_provider().name == "mock"


def test_get_provider_unwired_raises(monkeypatch):
    monkeypatch.setenv("STX_BILLING_PROVIDER", "stripe")
    with pytest.raises(RuntimeError):
        get_provider()
