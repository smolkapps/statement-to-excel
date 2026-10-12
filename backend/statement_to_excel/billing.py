"""Page metering and durable Stripe TEST Checkout. Never stores statements.

Purchases are granted only by verified Stripe webhooks. Checkout request keys,
provider sessions, account allowances, and entitlement grants persist in SQLite;
a grant and its deduplication marker commit in the same database transaction.
Production must mount STX_BILLING_DATABASE on durable shared storage (single host).
Live Stripe keys are deliberately rejected until Michael approves a future change.
"""

from __future__ import annotations

import os
import hashlib
import json
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path
from urllib.parse import urlparse
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
    pro: bool = False

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
    _lock: threading.Lock = field(default_factory=threading.RLock, repr=False)
    _conversion_charges: Dict[str, tuple] = field(default_factory=dict, repr=False)

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

    def charge_pages_once(self, account_id: str, pages: int, key: str, fingerprint: str) -> dict:
        """Debit one conversion retry group; retain metadata, never statements."""
        with self._lock:
            prior = self._conversion_charges.get(key)
            if prior:
                if prior[:2] != (account_id, fingerprint):
                    raise ValueError("Idempotency key belongs to another conversion.")
                return dict(prior[2])
            charge = self.charge_pages(account_id, pages)
            self._conversion_charges[key] = (account_id, fingerprint, dict(charge))
            return charge

    def conversion_charge(self, account_id: str, key: str, fingerprint: str):
        with self._lock:
            prior = self._conversion_charges.get(key)
            if prior and prior[:2] != (account_id, fingerprint):
                raise ValueError("Idempotency key belongs to another conversion.")
            return dict(prior[2]) if prior else None


# --------------------------------------------------------------------------- #
# Persistent API ledger + payment coordination
# --------------------------------------------------------------------------- #
class BillingError(Exception):
    """Safe error suitable for an API response, without provider credentials."""

    def __init__(self, detail: str, status_code: int = 503):
        super().__init__(detail)
        self.status_code = status_code


class PersistentLedger(Ledger):
    """SQLite metadata only; no uploaded bytes, filenames or transaction rows."""

    def __init__(self, database_path: str):
        super().__init__()
        self.database_path = database_path
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, plan_id TEXT NOT NULL DEFAULT 'free',
                    credits INTEGER NOT NULL DEFAULT 0,
                    pages_used INTEGER NOT NULL DEFAULT 0,
                    pro INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS checkout_requests (
                    request_key TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                    sku TEXT NOT NULL, attempted_at REAL NOT NULL,
                    provider_key TEXT UNIQUE,
                    session_id TEXT UNIQUE, response TEXT,
                    state TEXT NOT NULL DEFAULT 'pending',
                    subscription_id TEXT, cycle_start INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS checkout_aliases (
                    request_key TEXT PRIMARY KEY, canonical_key TEXT NOT NULL,
                    account_id TEXT NOT NULL, sku TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entitlements (
                    session_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                    sku TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS webhook_events (
                    event_id TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS subscription_state (
                    subscription_id TEXT PRIMARY KEY,
                    cancelled INTEGER NOT NULL DEFAULT 0,
                    cycle_start INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS conversion_charges (
                    request_key TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, charge TEXT NOT NULL
                );
            """)
            # Local metadata schemas are forwards compatible across deploys.
            columns = {row['name'] for row in db.execute("PRAGMA table_info(checkout_requests)")}
            if 'provider_key' not in columns:
                db.execute("ALTER TABLE checkout_requests ADD COLUMN provider_key TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS checkout_provider_key ON checkout_requests(provider_key)")

    def connect(self):
        db = sqlite3.connect(self.database_path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def ensure_account(db, account_id):
        db.execute("INSERT OR IGNORE INTO accounts(id) VALUES (?)", (account_id,))

    @staticmethod
    def read_account(db, account_id):
        row = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        return Account(row['id'], row['plan_id'], row['credits'], row['pages_used'], bool(row['pro']))

    def get_or_create(self, account_id):
        with self.transaction() as db:
            self.ensure_account(db, account_id)
            return self.read_account(db, account_id)

    def set_plan(self, account_id, plan_id):
        if plan_id not in PLANS:
            raise KeyError(f"unknown plan: {plan_id}")
        with self.transaction() as db:
            self.ensure_account(db, account_id)
            db.execute("UPDATE accounts SET plan_id=?,pro=? WHERE id=?", (plan_id, int(plan_id != 'free'), account_id))
            return self.read_account(db, account_id)

    def add_credits(self, account_id, credits):
        if credits < 0:
            raise ValueError("credits must be >= 0")
        with self.transaction() as db:
            self.ensure_account(db, account_id)
            db.execute("UPDATE accounts SET credits=credits+? WHERE id=?", (credits, account_id))
            return self.read_account(db, account_id)

    def charge_pages(self, account_id, pages):
        if pages < 0:
            raise ValueError("pages must be >= 0")
        with self.transaction() as db:
            self.ensure_account(db, account_id)
            acct = self.read_account(db, account_id)
            quote = acct.quote(pages)
            if not quote['sufficient']:
                raise InsufficientCredits("insufficient credits")
            db.execute("UPDATE accounts SET pages_used=pages_used+?,credits=credits-? WHERE id=?", (quote['from_included'], quote['from_credits'], account_id))
            return dict(account=account_id, kind='charge', pages=pages,
                        from_included=quote['from_included'], from_credits=quote['from_credits'],
                        credits_after=quote['credits_after'])

    def reset_cycle(self, account_id):
        with self.transaction() as db:
            self.ensure_account(db, account_id)
            db.execute("UPDATE accounts SET pages_used=0 WHERE id=?", (account_id,))
            return self.read_account(db, account_id)

    def conversion_charge(self, account_id, key, fingerprint):
        with self.transaction() as db:
            prior = db.execute("SELECT * FROM conversion_charges WHERE request_key=?", (key,)).fetchone()
            if prior and (prior['account_id'], prior['fingerprint']) != (account_id, fingerprint):
                raise ValueError("Idempotency key belongs to another conversion.")
            return json.loads(prior['charge']) if prior else None

    def charge_pages_once(self, account_id, pages, key, fingerprint):
        if pages < 0:
            raise ValueError("pages must be >= 0")
        with self.transaction() as db:
            prior = db.execute("SELECT * FROM conversion_charges WHERE request_key=?", (key,)).fetchone()
            if prior:
                if (prior['account_id'], prior['fingerprint']) != (account_id, fingerprint):
                    raise ValueError("Idempotency key belongs to another conversion.")
                return json.loads(prior['charge'])
            self.ensure_account(db, account_id)
            acct = self.read_account(db, account_id)
            quote = acct.quote(pages)
            if not quote['sufficient']:
                raise InsufficientCredits("insufficient credits")
            db.execute("UPDATE accounts SET pages_used=pages_used+?,credits=credits-? WHERE id=?", (quote['from_included'], quote['from_credits'], account_id))
            charge = dict(account=account_id, kind='charge', pages=pages,
                          from_included=quote['from_included'], from_credits=quote['from_credits'], credits_after=quote['credits_after'])
            db.execute("INSERT INTO conversion_charges VALUES (?,?,?,?)", (key, account_id, fingerprint, json.dumps(charge)))
            return charge


class BillingProvider:
    name = "base"
    mode = "test"

    def create_checkout(self, account_id, sku, idempotency_key):
        raise NotImplementedError

    def verify_event(self, payload, signature):
        raise NotImplementedError


class StripeBillingProvider(BillingProvider):
    name = "stripe"

    def __init__(self, secret_key=None, webhook_secret=None, origin=None):
        self.secret_key = secret_key if secret_key is not None else os.getenv("STX_STRIPE_SECRET_KEY", "")
        self.webhook_secret = webhook_secret if webhook_secret is not None else os.getenv("STX_STRIPE_WEBHOOK_SECRET", "")
        self.origin = (origin or os.getenv("STX_CHECKOUT_ORIGIN", "http://localhost:5173")).rstrip('/')
        # There is no environment-variable bypass for live charges.
        if self.secret_key and not self.secret_key.startswith("sk_test_"):
            raise RuntimeError("Only Stripe sk_test_ keys are permitted; Michael must approve live charges.")
        parsed = urlparse(self.origin)
        if parsed.scheme not in {'https', 'http'} or not parsed.netloc or parsed.query or parsed.fragment or parsed.path not in {'', '/'}:
            raise RuntimeError("STX_CHECKOUT_ORIGIN must be an origin without a path.")
        if parsed.scheme == 'http' and parsed.hostname not in {'localhost', '127.0.0.1'}:
            raise RuntimeError("Checkout return origin must use HTTPS except localhost.")

    def check_configuration(self):
        if not self.secret_key or not self.webhook_secret.startswith('whsec_'):
            raise BillingError("Checkout is unavailable until Stripe test credentials and webhook are configured.")

    def create_checkout(self, account_id, sku, idempotency_key):
        self.check_configuration()
        if sku == 'free' or sku not in CREDIT_PACKS and sku not in PLANS:
            raise BillingError("Unknown paid product.", 400)
        import stripe
        if sku in CREDIT_PACKS:
            product = CREDIT_PACKS[sku]
            price = product.price_usd
            mode = 'payment'
        else:
            product = PLANS[sku]
            price = product.monthly_price_usd
            mode = 'subscription'
        price_data = {'currency': 'usd', 'unit_amount': int(price * 100),
                      'product_data': {'name': product.name}}
        if mode == 'subscription':
            price_data['recurring'] = {'interval': 'month'}
        try:
            session = stripe.checkout.Session.create(
                api_key=self.secret_key, idempotency_key=idempotency_key,
                mode=mode, payment_method_types=['card'],
                line_items=[{'price_data': price_data, 'quantity': 1}],
                client_reference_id=account_id,
                metadata={'account_id': account_id, 'sku': sku, 'purchase_key': idempotency_key},
                success_url=self.origin + '/?checkout=success&session_id={CHECKOUT_SESSION_ID}',
                cancel_url=self.origin + '/?checkout=cancelled',
            )
        except stripe.StripeError as exc:
            raise BillingError("Checkout could not be opened. Retry this same purchase.") from exc
        return {'session_id': session['id'], 'checkout_url': session['url'],
                'provider': self.name, 'mode': 'test'}

    def verify_event(self, payload, signature):
        if not self.webhook_secret.startswith('whsec_'):
            raise BillingError("Stripe webhook is not configured.")
        import stripe
        try:
            return stripe.Webhook.construct_event(payload, signature, self.webhook_secret, tolerance=300)
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise BillingError("Invalid webhook signature.", 400) from exc


class MockBillingProvider(BillingProvider):
    """Explicit unit-test double; never selected by deployment configuration."""
    name = "mock"

    def __init__(self):
        self._pending = {}
        self._keys = {}
        self._lock = threading.Lock()

    def create_checkout(self, account_id, sku, idempotency_key=None):
        if sku not in CREDIT_PACKS and sku not in PLANS:
            raise KeyError(f"unknown sku: {sku}")
        with self._lock:
            if idempotency_key and idempotency_key in self._keys:
                return self._keys[idempotency_key]
            session_id = 'cs_mock_' + uuid.uuid4().hex
            self._pending[session_id] = {'account_id': account_id, 'sku': sku}
            response = {'session_id': session_id, 'checkout_url': f'https://mock.local/checkout/{session_id}', 'provider': self.name, 'mode': 'test'}
            if idempotency_key:
                self._keys[idempotency_key] = response
            return response

    def fulfill(self, ledger, session_id):
        with self._lock:
            intent = self._pending.pop(session_id, None)
        if intent is None:
            raise KeyError(f"unknown or already-fulfilled session: {session_id}")
        if intent['sku'] in CREDIT_PACKS:
            return ledger.add_credits(intent['account_id'], CREDIT_PACKS[intent['sku']].credits)
        return ledger.set_plan(intent['account_id'], intent['sku'])


def create_checkout(ledger, provider, account_id, sku, request_key):
    """Reserve a durable request before touching Stripe; retry its original key.

    Stripe retains keys at least 24 hours. An ambiguous request older than 23
    hours fails closed for owner reconciliation, rather than risking a second
    payment after Stripe's key retention window.
    """
    if not request_key or len(request_key) < 16 or len(request_key) > 200:
        raise BillingError("A stable Idempotency-Key of 16-200 characters is required.", 400)
    if sku == 'free' or sku not in CREDIT_PACKS and sku not in PLANS:
        raise BillingError("Unknown paid product.", 400)
    # A deterministic local configuration error cannot have reached Stripe;
    # do not leave a pending purchase that prevents choosing another plan.
    preflight = getattr(provider, 'check_configuration', None)
    if preflight:
        preflight()
    if not isinstance(ledger, PersistentLedger):
        # Compatibility for the explicitly injected pure unit-test ledger.
        return provider.create_checkout(account_id, sku, request_key)
    with ledger.transaction() as db:
        row = db.execute("SELECT * FROM checkout_requests WHERE request_key=?", (request_key,)).fetchone()
        alias = db.execute("SELECT * FROM checkout_aliases WHERE request_key=?", (request_key,)).fetchone()
        if alias:
            if (alias['account_id'], alias['sku']) != (account_id, sku):
                raise BillingError("Idempotency key already belongs to another purchase.", 409)
            row = db.execute("SELECT * FROM checkout_requests WHERE request_key=?", (alias['canonical_key'],)).fetchone()
        if row and (row['account_id'], row['sku']) != (account_id, sku):
            raise BillingError("Idempotency key already belongs to another purchase.", 409)
        if not row:
            # An active subscription must never be purchased twice.
            if sku in PLANS:
                active = db.execute("SELECT 1 FROM checkout_requests WHERE account_id=? AND subscription_id IS NOT NULL AND state='fulfilled'", (account_id,)).fetchone()
                if active:
                    raise BillingError("A subscription is already active; contact the owner to change plans.", 409)
                pending = db.execute("SELECT sku FROM checkout_requests WHERE account_id=? AND state='pending' AND sku IN ('starter','business','firm')", (account_id,)).fetchone()
                if pending and pending['sku'] != sku:
                    raise BillingError("Another plan checkout is pending; finish it or wait for it to expire before changing plans.", 409)
            row = db.execute("SELECT * FROM checkout_requests WHERE account_id=? AND sku=? AND state='pending' ORDER BY attempted_at LIMIT 1", (account_id, sku)).fetchone()
            if row:
                db.execute("INSERT INTO checkout_aliases VALUES (?,?,?,?)", (request_key, row['request_key'], account_id, sku))
            else:
                provider_key = 'stx-' + hashlib.sha256(request_key.encode()).hexdigest()
                db.execute("INSERT INTO checkout_requests(request_key,account_id,sku,attempted_at,provider_key) VALUES (?,?,?,?,?)", (request_key, account_id, sku, time.time(), provider_key))
    # Separate transaction preserves the reservation if a network failure rolls back.
    with ledger.transaction() as db:
        alias = db.execute("SELECT canonical_key FROM checkout_aliases WHERE request_key=?", (request_key,)).fetchone()
        canonical = alias['canonical_key'] if alias else request_key
        row = db.execute("SELECT * FROM checkout_requests WHERE request_key=?", (canonical,)).fetchone()
        if row['state'] == 'expired':
            raise BillingError("This checkout expired; start a new purchase.", 409)
        if row['state'] in {'fulfilled', 'cancelled'} and not row['response']:
            raise BillingError("This purchase is already completed; refresh its status.", 409)
        if row['response']:
            return json.loads(row['response'])
        if time.time() - row['attempted_at'] > 23 * 60 * 60:
            raise BillingError("Payment status is uncertain; owner reconciliation is required before retrying.", 409)
        stripe_key = row['provider_key'] or 'stx-' + hashlib.sha256(canonical.encode()).hexdigest()
        db.execute("UPDATE checkout_requests SET provider_key=? WHERE request_key=?", (stripe_key, canonical))
        response = provider.create_checkout(account_id, sku, stripe_key)
        if not response.get('session_id') or not response.get('checkout_url'):
            raise BillingError("Payment provider returned an incomplete checkout.")
        db.execute("UPDATE checkout_requests SET session_id=?,response=? WHERE request_key=?", (response['session_id'], json.dumps(response), canonical))
        return response


def checkout_status(ledger, session_id, account_id):
    if not isinstance(ledger, PersistentLedger):
        raise BillingError("Durable billing storage is required.")
    with ledger.transaction() as db:
        row = db.execute("SELECT * FROM checkout_requests WHERE session_id=? AND account_id=?", (session_id, account_id)).fetchone()
        if not row:
            raise BillingError("Checkout was not found for this account.", 404)
        return {'session_id': session_id, 'sku': row['sku'], 'status': row['state']}


def apply_webhook(ledger, event):
    """Exactly-once grant, atomic with its marker, based on paid signed events."""
    if not isinstance(ledger, PersistentLedger):
        raise BillingError("Durable billing storage is required.")
    if event.get('livemode') is not False:
        raise BillingError("Live payment events are not permitted.", 400)
    event_id = event.get('id')
    if not event_id:
        raise BillingError("Webhook event id is required.", 400)
    session = event.get('data', {}).get('object', {})
    kind = event.get('type')
    with ledger.transaction() as db:
        if db.execute("SELECT 1 FROM webhook_events WHERE event_id=?", (event_id,)).fetchone():
            return {'received': True, 'granted': False}
        granted = False
        if kind in {'checkout.session.completed', 'checkout.session.async_payment_succeeded'}:
            if session.get('payment_status') != 'paid' or session.get('livemode') is not False:
                # Never grant on a redirect, failed request, unpaid session or live event.
                return {'received': True, 'granted': False}
            row = db.execute("SELECT * FROM checkout_requests WHERE session_id=?", (session.get('id'),)).fetchone()
            metadata = session.get('metadata') or {}
            if not row:
                # A signed event can recover a session created before API failure.
                row = db.execute("SELECT * FROM checkout_requests WHERE provider_key=?", (metadata.get('purchase_key'),)).fetchone()
                if not row or row['session_id']:
                    raise BillingError("Checkout session is not recorded or conflicts with its purchase.")
            if (metadata.get('account_id'), metadata.get('sku')) != (row['account_id'], row['sku']):
                raise BillingError("Checkout metadata does not match its purchase.", 400)
            expected_mode = 'payment' if row['sku'] in CREDIT_PACKS else 'subscription'
            if session.get('mode') != expected_mode or (expected_mode == 'subscription' and not session.get('subscription')):
                raise BillingError("Checkout mode does not match its purchase.", 400)
            price = CREDIT_PACKS[row['sku']].price_usd if expected_mode == 'payment' else PLANS[row['sku']].monthly_price_usd
            if session.get('currency') != 'usd' or session.get('amount_total') != int(price * 100):
                raise BillingError("Paid amount does not match the configured product.", 400)
            session_id = session.get('id')
            if not session_id:
                raise BillingError("Checkout session id is required.", 400)
            db.execute("UPDATE checkout_requests SET session_id=? WHERE request_key=?", (session_id, row['request_key']))
            sub = session.get('subscription')
            prior_sub = db.execute("SELECT * FROM subscription_state WHERE subscription_id=?", (sub,)).fetchone() if sub else None
            if prior_sub and prior_sub['cancelled']:
                db.execute("UPDATE checkout_requests SET state='cancelled',subscription_id=? WHERE request_key=?", (sub, row['request_key']))
                db.execute("INSERT INTO webhook_events VALUES (?)", (event_id,))
                return {'received': True, 'granted': False}
            inserted = db.execute("INSERT OR IGNORE INTO entitlements VALUES (?,?,?)", (session_id, row['account_id'], row['sku'])).rowcount
            if inserted:
                ledger.ensure_account(db, row['account_id'])
                if row['sku'] in CREDIT_PACKS:
                    db.execute("UPDATE accounts SET credits=credits+?,pro=1 WHERE id=?", (CREDIT_PACKS[row['sku']].credits, row['account_id']))
                else:
                    db.execute("UPDATE accounts SET plan_id=?,pro=1,pages_used=0 WHERE id=?", (row['sku'], row['account_id']))
                cycle = prior_sub['cycle_start'] if prior_sub else 0
                db.execute("UPDATE checkout_requests SET state='fulfilled',subscription_id=?,cycle_start=? WHERE session_id=?", (sub, cycle, session_id))
                granted = True
        elif kind == 'checkout.session.expired':
            row = db.execute("SELECT * FROM checkout_requests WHERE session_id=?", (session.get('id'),)).fetchone()
            metadata = session.get('metadata') or {}
            if not row and metadata.get('purchase_key'):
                row = db.execute("SELECT * FROM checkout_requests WHERE provider_key=?", (metadata['purchase_key'],)).fetchone()
                if row and not row['session_id'] and (metadata.get('account_id'), metadata.get('sku')) == (row['account_id'], row['sku']):
                    db.execute("UPDATE checkout_requests SET session_id=? WHERE request_key=?", (session.get('id'), row['request_key']))
            db.execute("UPDATE checkout_requests SET state='expired' WHERE session_id=? AND state='pending'", (session.get('id'),))
        elif kind == 'customer.subscription.deleted':
            if not session.get('id'):
                raise BillingError("Subscription id is required.", 400)
            db.execute("INSERT INTO subscription_state(subscription_id,cancelled) VALUES (?,1) ON CONFLICT(subscription_id) DO UPDATE SET cancelled=1", (session['id'],))
            row = db.execute("SELECT * FROM checkout_requests WHERE subscription_id=? AND state='fulfilled'", (session.get('id'),)).fetchone()
            if row:
                db.execute("UPDATE checkout_requests SET state='cancelled' WHERE subscription_id=?", (session['id'],))
                packs = db.execute("SELECT 1 FROM entitlements WHERE account_id=? AND sku IN ('pack_50','pack_200','pack_1000')", (row['account_id'],)).fetchone()
                db.execute("UPDATE accounts SET plan_id='free',pro=?,pages_used=3 WHERE id=?", (int(bool(packs)), row['account_id']))
        elif kind == 'invoice.paid':
            # Stripe v2025 nests subscription under parent; older versions expose it directly.
            subscription = session.get('subscription') or session.get('parent', {}).get('subscription_details', {}).get('subscription')
            row = db.execute("SELECT * FROM checkout_requests WHERE subscription_id=? AND state='fulfilled'", (subscription,)).fetchone()
            period = session.get('period_start', 0)
            if subscription and session.get('billing_reason') == 'subscription_cycle':
                db.execute("INSERT INTO subscription_state(subscription_id,cycle_start) VALUES (?,?) ON CONFLICT(subscription_id) DO UPDATE SET cycle_start=max(cycle_start,excluded.cycle_start)", (subscription, period))
            if row and session.get('billing_reason') == 'subscription_cycle' and period > row['cycle_start']:
                db.execute("UPDATE accounts SET pages_used=0 WHERE id=?", (row['account_id'],))
                db.execute("UPDATE checkout_requests SET cycle_start=? WHERE session_id=?", (period, row['session_id']))
        db.execute("INSERT INTO webhook_events VALUES (?)", (event_id,))
        return {'received': True, 'granted': granted}


def get_provider():
    name = os.getenv('STX_BILLING_PROVIDER', 'stripe').lower()
    if name != 'stripe':
        raise RuntimeError("Only Stripe test billing is supported; mock is a unit-test double.")
    return StripeBillingProvider()
