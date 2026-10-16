"""Page metering and durable app-owned Stripe billing. Never stores statements.

Purchases are granted only by verified Stripe webhooks. Checkout request keys,
provider sessions, account allowances, and entitlement grants persist in SQLite;
a grant and its deduplication marker commit in the same database transaction.
Production must mount STX_BILLING_DATABASE on durable shared storage (single host).
Explicit test/live modes use separate mode-bound durable databases.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path
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

# Conversion retries are a short-lived convenience, separate from the durable
# purchase keys required to prevent duplicate financial payments.
CONVERSION_IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60


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
    billing_hold: bool = False

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
            "sufficient": from_credits <= self.credits and not self.billing_hold,
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

    def get_if_exists(self, account_id: str) -> Account:
        """Read an account or return an ephemeral default without persisting it."""
        with self._lock:
            return self.accounts.get(account_id) or Account(id=account_id)

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
        """Debit a retry group once within 24 hours; never retain statements."""
        with self._lock:
            self.purge_conversion_charges()
            prior = self._conversion_charges.get(key)
            if prior:
                if prior[:2] != (account_id, fingerprint):
                    raise ValueError("Idempotency key belongs to another conversion.")
                return dict(prior[2])
            charge = self.charge_pages(account_id, pages)
            self._conversion_charges[key] = (account_id, fingerprint, dict(charge), time.time())
            return charge

    def conversion_charge(self, account_id: str, key: str, fingerprint: str):
        with self._lock:
            self.purge_conversion_charges()
            prior = self._conversion_charges.get(key)
            if prior and prior[:2] != (account_id, fingerprint):
                raise ValueError("Idempotency key belongs to another conversion.")
            return dict(prior[2]) if prior else None

    def purge_conversion_charges(self) -> int:
        """Opportunistic cleanup with no access-based extension of retention."""
        with self._lock:
            cutoff = time.time() - CONVERSION_IDEMPOTENCY_TTL_SECONDS
            expired = [key for key, row in self._conversion_charges.items()
                       if len(row) < 4 or row[3] < cutoff]
            for key in expired:
                del self._conversion_charges[key]
            return len(expired)


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

    def __init__(self, database_path: str, mode: str = "test"):
        super().__init__()
        self.mode = mode
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
                    fingerprint TEXT NOT NULL, charge TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS stx_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS stx_customers (
                    account_id TEXT NOT NULL, mode TEXT NOT NULL,
                    binding_ref TEXT NOT NULL UNIQUE, customer_id TEXT UNIQUE,
                    attempted_at REAL NOT NULL, PRIMARY KEY(account_id,mode)
                );
                CREATE TABLE IF NOT EXISTS stx_subscriptions (
                    subscription_id TEXT PRIMARY KEY, purchase_ref TEXT NOT NULL UNIQUE,
                    account_id TEXT NOT NULL, customer_id TEXT NOT NULL, mode TEXT NOT NULL,
                    sku TEXT NOT NULL, paid_through INTEGER NOT NULL DEFAULT 0,
                    cycle_start INTEGER NOT NULL DEFAULT 0,
                    terminal INTEGER NOT NULL DEFAULT 0, blocked INTEGER NOT NULL DEFAULT 0,
                    cancel_at_period_end INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'incomplete'
                );
                CREATE TABLE IF NOT EXISTS stx_payments (
                    payment_intent TEXT PRIMARY KEY, purchase_ref TEXT NOT NULL,
                    customer_id TEXT NOT NULL, mode TEXT NOT NULL, amount INTEGER NOT NULL,
                    charge_id TEXT UNIQUE, invoice_id TEXT, subscription_id TEXT,
                    reversed INTEGER NOT NULL DEFAULT 0, disputed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS stx_cycles (
                    invoice_id TEXT PRIMARY KEY, subscription_id TEXT NOT NULL,
                    period_start INTEGER NOT NULL, period_end INTEGER NOT NULL,
                    amount INTEGER NOT NULL, used_pages INTEGER NOT NULL DEFAULT 0,
                    reversed INTEGER NOT NULL DEFAULT 0,
                    granted INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(subscription_id,period_start)
                );
                CREATE TABLE IF NOT EXISTS stx_credit_lots (
                    purchase_ref TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                    granted INTEGER NOT NULL, remaining INTEGER NOT NULL,
                    consumed INTEGER NOT NULL DEFAULT 0, revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS stx_holds (
                    purchase_ref TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                    reason TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS stx_actions (
                    subscription_id TEXT PRIMARY KEY, purchase_ref TEXT NOT NULL,
                    mode TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt REAL NOT NULL DEFAULT 0,
                    complete INTEGER NOT NULL DEFAULT 0, last_error TEXT
                );
            """)
            # Local metadata schemas are forwards compatible across deploys.
            columns = {row['name'] for row in db.execute("PRAGMA table_info(checkout_requests)")}
            if 'provider_key' not in columns:
                db.execute("ALTER TABLE checkout_requests ADD COLUMN provider_key TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS checkout_provider_key ON checkout_requests(provider_key)")
            # Serialize migration across workers opening an old database. Old
            # fingerprints have unknowable ages: expire them, never restart the
            # retention clock. Existing usage debits and purchases stay intact.
            db.execute("BEGIN IMMEDIATE")
            try:
                columns = {row['name'] for row in db.execute("PRAGMA table_info(conversion_charges)")}
                if 'created_at' not in columns:
                    db.execute("ALTER TABLE conversion_charges ADD COLUMN created_at REAL")
                db.execute("DELETE FROM conversion_charges WHERE created_at IS NULL")
                db.execute("CREATE INDEX IF NOT EXISTS conversion_charges_created_at ON conversion_charges(created_at)")
                columns = {row['name'] for row in db.execute("PRAGMA table_info(checkout_requests)")}
                for name, definition in (("app", "TEXT"), ("mode", "TEXT"),
                                         ("purchase_ref", "TEXT"), ("customer_id", "TEXT")):
                    if name not in columns:
                        db.execute(f"ALTER TABLE checkout_requests ADD COLUMN {name} {definition}")
                db.execute("CREATE UNIQUE INDEX IF NOT EXISTS stx_purchase_ref ON checkout_requests(purchase_ref)")
                if 'granted' not in {row['name'] for row in db.execute('PRAGMA table_info(stx_cycles)')}:
                    db.execute('ALTER TABLE stx_cycles ADD COLUMN granted INTEGER NOT NULL DEFAULT 0')
                prior = db.execute("SELECT value FROM stx_settings WHERE key='billing_mode'").fetchone()
                legacy = any(db.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone()
                             for table in ('accounts', 'checkout_requests', 'entitlements', 'subscription_state'))
                if mode not in {'test', 'live'} or prior and prior['value'] != mode or not prior and legacy and mode != 'test':
                    raise RuntimeError("Billing database mode conflicts with configured mode; use separate test/live databases.")
                db.execute("INSERT OR IGNORE INTO stx_settings VALUES ('billing_mode',?)", (mode,))
                db.commit()
            except BaseException:
                db.rollback()
                raise

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

    def read_account(self, db, account_id):
        from .payments import refresh_account_access
        refresh_account_access(db, account_id)
        row = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        held = db.execute("SELECT 1 FROM stx_holds WHERE account_id=? AND resolved=0", (account_id,)).fetchone()
        return Account(row['id'], row['plan_id'], row['credits'], row['pages_used'], bool(row['pro']), bool(held))

    def require_mode(self, mode):
        if mode != self.mode:
            raise BillingError("Billing mode does not match this database.")

    @staticmethod
    def record_spend(db, account_id, included, credits):
        from .payments import record_spend
        record_spend(db, account_id, included, credits)

    def get_or_create(self, account_id):
        with self.transaction() as db:
            self.ensure_account(db, account_id)
            return self.read_account(db, account_id)

    def get_if_exists(self, account_id):
        with self.transaction() as db:
            found = db.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone()
            return self.read_account(db, account_id) if found else Account(id=account_id)

    def has_customer(self, account_id):
        with self.transaction() as db:
            return bool(db.execute("SELECT 1 FROM stx_customers WHERE account_id=? AND mode=? AND customer_id IS NOT NULL", (account_id, self.mode)).fetchone())

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
            self.record_spend(db, account_id, quote['from_included'], quote['from_credits'])
            return dict(account=account_id, kind='charge', pages=pages,
                        from_included=quote['from_included'], from_credits=quote['from_credits'],
                        credits_after=quote['credits_after'])

    def reset_cycle(self, account_id):
        with self.transaction() as db:
            self.ensure_account(db, account_id)
            db.execute("UPDATE accounts SET pages_used=0 WHERE id=?", (account_id,))
            return self.read_account(db, account_id)

    def conversion_charge(self, account_id, key, fingerprint):
        self.purge_conversion_charges()
        try:
            with self.transaction() as db:
                self._purge_conversion_charges(db)
                prior = db.execute("SELECT * FROM conversion_charges WHERE request_key=?", (key,)).fetchone()
                if prior and (prior['account_id'], prior['fingerprint']) != (account_id, fingerprint):
                    raise ValueError("Idempotency key belongs to another conversion.")
                return json.loads(prior['charge']) if prior else None
        except ValueError:
            # Cleanup inside a rejected lookup rolled back with the transaction.
            self.purge_conversion_charges()
            raise

    def purge_conversion_charges(self) -> int:
        with self.transaction() as db:
            return self._purge_conversion_charges(db)

    @staticmethod
    def _purge_conversion_charges(db) -> int:
        cutoff = time.time() - CONVERSION_IDEMPOTENCY_TTL_SECONDS
        return db.execute("DELETE FROM conversion_charges WHERE created_at IS NULL OR created_at < ?", (cutoff,)).rowcount

    def charge_pages_once(self, account_id, pages, key, fingerprint):
        self.purge_conversion_charges()
        if pages < 0:
            raise ValueError("pages must be >= 0")
        try:
            with self.transaction() as db:
                # A concurrent operation may have held the lock across expiry.
                self._purge_conversion_charges(db)
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
                self.record_spend(db, account_id, quote['from_included'], quote['from_credits'])
                charge = dict(account=account_id, kind='charge', pages=pages,
                              from_included=quote['from_included'], from_credits=quote['from_credits'], credits_after=quote['credits_after'])
                db.execute("INSERT INTO conversion_charges(request_key,account_id,fingerprint,charge,created_at) VALUES (?,?,?,?,?)", (key, account_id, fingerprint, json.dumps(charge), time.time()))
                return charge
        except (ValueError, InsufficientCredits):
            # Keep privacy cleanup committed even when a quota/conflict failure
            # rolls back an expiry that occurred while waiting for the lock.
            self.purge_conversion_charges()
            raise


class BillingProvider:
    name = "base"
    mode = "test"

    def create_checkout(self, account_id, sku, idempotency_key):
        raise NotImplementedError

    def verify_event(self, payload, signature):
        raise NotImplementedError


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



# Re-export the public API while keeping document metering independent of Stripe.
from .payments import (StripeBillingProvider, create_checkout, checkout_status,
                       apply_webhook, create_portal, get_provider)
