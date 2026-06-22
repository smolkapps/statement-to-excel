"""Self-contained metering / monetization for statement-to-excel.

The product sells at *business* rates via two mechanisms (no ads, no affiliate):

* **Prepaid credits** — buy a pack, spend 1 credit per processed statement page.
* **Subscriptions** — a monthly plan grants an included page allowance that
  resets each cycle; overage spends prepaid credits.

This module is the pure, deterministic core of that model. Real payment capture
is *stubbed behind an env var* (``STX_BILLING_PROVIDER``): the default
``"mock"`` provider just records intents in memory so the API and its tests run
with no Stripe key. Swapping in a real provider is a single class.

Pricing here is the source of truth shared with the frontend (kept in sync by a
parity test that reads ``frontend/src/pricing.json``).
"""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional

__all__ = [
    "Plan",
    "CreditPack",
    "PLANS",
    "CREDIT_PACKS",
    "Account",
    "InsufficientCredits",
    "Ledger",
    "BillingProvider",
    "MockBillingProvider",
    "get_provider",
    "PRICING",
]


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    monthly_price_usd: Decimal
    included_pages: int  # pages included per billing cycle
    overage_per_page_usd: Decimal


@dataclass(frozen=True)
class CreditPack:
    id: str
    name: str
    credits: int  # 1 credit == 1 page
    price_usd: Decimal

    @property
    def per_credit_usd(self) -> Decimal:
        return (self.price_usd / self.credits).quantize(Decimal("0.0001"))


# Business-tier pricing (USD). Free tier exists for trial/SEO, the money is in
# Business/Firm. These mirror frontend/src/pricing.json exactly.
PLANS: Dict[str, Plan] = {
    "free": Plan("free", "Free", Decimal("0"), 3, Decimal("0")),
    "starter": Plan("starter", "Starter", Decimal("29"), 120, Decimal("0.30")),
    "business": Plan("business", "Business", Decimal("79"), 500, Decimal("0.20")),
    "firm": Plan("firm", "Firm", Decimal("199"), 2000, Decimal("0.12")),
}

CREDIT_PACKS: Dict[str, CreditPack] = {
    "pack_50": CreditPack("pack_50", "50 credits", 50, Decimal("30")),
    "pack_200": CreditPack("pack_200", "200 credits", 200, Decimal("100")),
    "pack_1000": CreditPack("pack_1000", "1,000 credits", 1000, Decimal("400")),
}


def _catalog_dict() -> dict:
    return {
        "plans": [
            {
                "id": p.id,
                "name": p.name,
                "monthly_price_usd": f"{p.monthly_price_usd:f}",
                "included_pages": p.included_pages,
                "overage_per_page_usd": f"{p.overage_per_page_usd:f}",
            }
            for p in PLANS.values()
        ],
        "credit_packs": [
            {
                "id": c.id,
                "name": c.name,
                "credits": c.credits,
                "price_usd": f"{c.price_usd:f}",
                "per_credit_usd": f"{c.per_credit_usd:f}",
            }
            for c in CREDIT_PACKS.values()
        ],
    }


PRICING = _catalog_dict()


# --------------------------------------------------------------------------- #
# Account state + metering
# --------------------------------------------------------------------------- #
class InsufficientCredits(Exception):
    """Raised when an account cannot cover a charge."""


@dataclass
class Account:
    """A single customer's metering state."""

    id: str
    plan_id: str = "free"
    credits: int = 0  # prepaid credit balance
    pages_used_this_cycle: int = 0

    @property
    def plan(self) -> Plan:
        return PLANS[self.plan_id]

    def included_remaining(self) -> int:
        return max(0, self.plan.included_pages - self.pages_used_this_cycle)

    def can_process(self, pages: int) -> bool:
        if pages <= 0:
            return True
        need_from_credits = max(0, pages - self.included_remaining())
        return need_from_credits <= self.credits

    def quote(self, pages: int) -> dict:
        """How a charge of ``pages`` would be covered, without applying it."""
        from_included = min(pages, self.included_remaining())
        from_credits = max(0, pages - from_included)
        return {
            "pages": pages,
            "from_included": from_included,
            "from_credits": from_credits,
            "credits_after": self.credits - from_credits,
            "sufficient": from_credits <= self.credits,
        }


@dataclass
class Ledger:
    """In-memory accounts + a charge log. Thread-safe for the API's needs."""

    accounts: Dict[str, Account] = field(default_factory=dict)
    log: List[dict] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def get_or_create(self, account_id: str) -> Account:
        with self._lock:
            acct = self.accounts.get(account_id)
            if acct is None:
                acct = Account(id=account_id)
                self.accounts[account_id] = acct
            return acct

    def set_plan(self, account_id: str, plan_id: str) -> Account:
        if plan_id not in PLANS:
            raise KeyError(f"unknown plan: {plan_id}")
        acct = self.get_or_create(account_id)
        with self._lock:
            acct.plan_id = plan_id
            return acct

    def add_credits(self, account_id: str, credits: int) -> Account:
        if credits < 0:
            raise ValueError("credits must be >= 0")
        acct = self.get_or_create(account_id)
        with self._lock:
            acct.credits += credits
            self.log.append(
                {"account": account_id, "kind": "topup", "credits": credits}
            )
            return acct

    def charge_pages(self, account_id: str, pages: int) -> dict:
        """Apply a charge of ``pages``: spend included allowance first, then
        prepaid credits. Raises :class:`InsufficientCredits` if it cannot cover
        the cost, leaving state unchanged."""
        if pages < 0:
            raise ValueError("pages must be >= 0")
        acct = self.get_or_create(account_id)
        with self._lock:
            from_included = min(pages, acct.included_remaining())
            from_credits = pages - from_included
            if from_credits > acct.credits:
                raise InsufficientCredits(
                    f"need {from_credits} credits, have {acct.credits}"
                )
            acct.pages_used_this_cycle += from_included
            acct.credits -= from_credits
            entry = {
                "account": account_id,
                "kind": "charge",
                "pages": pages,
                "from_included": from_included,
                "from_credits": from_credits,
                "credits_after": acct.credits,
            }
            self.log.append(entry)
            return entry

    def reset_cycle(self, account_id: str) -> Account:
        acct = self.get_or_create(account_id)
        with self._lock:
            acct.pages_used_this_cycle = 0
            return acct


# --------------------------------------------------------------------------- #
# Payment provider (stubbed behind an env var)
# --------------------------------------------------------------------------- #
class BillingProvider:
    """Interface a real provider (Stripe, etc.) would implement."""

    name = "base"

    def create_checkout(self, account_id: str, sku: str) -> dict:  # pragma: no cover
        raise NotImplementedError

    def fulfill(self, ledger: Ledger, session_id: str) -> Account:  # pragma: no cover
        raise NotImplementedError


class MockBillingProvider(BillingProvider):
    """No-network provider used by default and in tests.

    ``create_checkout`` records a pending intent and returns a fake URL; calling
    ``fulfill`` grants the purchased credits / plan. This lets the whole
    purchase->grant flow be unit-tested deterministically with no Stripe key.
    """

    name = "mock"

    def __init__(self) -> None:
        self._pending: Dict[str, dict] = {}

    def create_checkout(self, account_id: str, sku: str) -> dict:
        if sku not in CREDIT_PACKS and sku not in PLANS:
            raise KeyError(f"unknown sku: {sku}")
        session_id = "cs_mock_" + uuid.uuid4().hex[:16]
        self._pending[session_id] = {"account_id": account_id, "sku": sku}
        return {
            "session_id": session_id,
            "checkout_url": f"https://mock.local/checkout/{session_id}",
            "provider": self.name,
        }

    def fulfill(self, ledger: Ledger, session_id: str) -> Account:
        intent = self._pending.pop(session_id, None)
        if intent is None:
            raise KeyError(f"unknown or already-fulfilled session: {session_id}")
        account_id, sku = intent["account_id"], intent["sku"]
        if sku in CREDIT_PACKS:
            return ledger.add_credits(account_id, CREDIT_PACKS[sku].credits)
        return ledger.set_plan(account_id, sku)


def get_provider() -> BillingProvider:
    """Return the configured provider. Default ``mock``; ``stripe`` reserved.

    Only ``mock`` is implemented in this self-contained build; selecting
    ``stripe`` without the integration raises a clear error so deploys fail loud.
    """
    name = os.environ.get("STX_BILLING_PROVIDER", "mock").lower()
    if name == "mock":
        return MockBillingProvider()
    raise RuntimeError(
        f"Billing provider '{name}' is not wired in this build. "
        "Set STX_BILLING_PROVIDER=mock or implement the provider."
    )
