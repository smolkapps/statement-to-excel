"""Owned Stripe purchases. No document data and no browser-return grants.

Snapshot webhooks and requests use the same explicitly pinned Stripe contract.
SQLite transactions serialize financial mutations; provider idempotency keys are
reserved durably before a network request. Test/live databases cannot be mixed.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from urllib.parse import urlsplit

from .billing import BillingError, BillingProvider, CREDIT_PACKS, PLANS

APP = "statement-to-excel"
API_VERSION = "2026-02-25.clover"
CANONICAL_ORIGIN = "https://statement-to-excel.apps.smolkin.org"
EVENTS = frozenset({
    "checkout.session.completed", "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed", "checkout.session.expired",
    "invoice.paid", "invoice.payment_failed", "customer.subscription.updated",
    "customer.subscription.deleted", "charge.refunded", "charge.dispute.created",
    "charge.dispute.updated", "charge.dispute.closed",
})


def require(condition, detail="Conflicting owned payment evidence.", code=400):
    if not condition:
        raise BillingError(detail, code)


def ident(value):
    return value.get("id") if isinstance(value, dict) else value


def amount(sku):
    price = CREDIT_PACKS[sku].price_usd if sku in CREDIT_PACKS else PLANS[sku].monthly_price_usd
    return int(price * 100)


def metadata(ref):
    return {"app": APP, "purchase_ref": ref}


class StripeBillingProvider(BillingProvider):
    name = "stripe"

    def __init__(self, secret_key=None, webhook_secret=None, checkout_origin=None,
                 mode=None, portal_configuration=None, client=None):
        import stripe
        self.mode = mode or os.getenv("STX_STRIPE_MODE", "test")
        self.secret_key = secret_key if secret_key is not None else os.getenv("STX_STRIPE_SECRET_KEY", "")
        self.webhook_secret = webhook_secret if webhook_secret is not None else os.getenv("STX_STRIPE_WEBHOOK_SECRET", "")
        self.origin = (checkout_origin or os.getenv("STX_CHECKOUT_ORIGIN", CANONICAL_ORIGIN)).rstrip("/")
        self.portal_configuration = portal_configuration if portal_configuration is not None else os.getenv("STX_STRIPE_PORTAL_CONFIGURATION", "")
        require(self.mode in {"test", "live"}, "Invalid Stripe mode.", 503)
        require(not self.secret_key or re.fullmatch(f"sk_{self.mode}_[A-Za-z0-9_]{{8,}}", self.secret_key), "Stripe key does not match configured mode.", 503)
        require(not self.webhook_secret or re.fullmatch(r"whsec_[A-Za-z0-9_]{8,}", self.webhook_secret), "Invalid Stripe webhook configuration.", 503)
        parts = urlsplit(self.origin)
        local = self.mode == "test" and parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1"}
        require(self.origin == CANONICAL_ORIGIN or local and parts.path in {"", "/"} and not parts.query and not parts.fragment and not parts.username,
                "Checkout origin must be the canonical app origin (localhost only in test).", 503)
        self.origin = self.origin.rstrip("/")
        require(not self.portal_configuration or re.fullmatch(r"bpc_[A-Za-z0-9]+", self.portal_configuration), "Invalid portal configuration.", 503)
        self.checkout_available = bool(self.secret_key and self.webhook_secret)
        require(not self.checkout_available or self.portal_configuration,
                "Configured billing requires an app-specific hosted management configuration.", 503)
        self.client = client
        if self.checkout_available and client is None:
            self.client = stripe.StripeClient(self.secret_key, stripe_version=API_VERSION,
                max_network_retries=0, http_client=stripe.RequestsClient(timeout=10))

    def call(self, resource, method, *args, **kwargs):
        try:
            target = self.client.v1
            for part in resource.split("."):
                target = getattr(target, part)
            result = getattr(target, method)(*args, **kwargs)
            return result.to_dict_recursive() if hasattr(result, "to_dict_recursive") else result
        except BillingError:
            raise
        except Exception as exc:
            # Provider errors may contain customer/payment details. Never expose them.
            raise BillingError("Payment service unavailable. Retry the same request.") from exc

    def verify_event(self, payload, signature):
        import stripe
        require(self.checkout_available, "Checkout is unavailable.", 503)
        try:
            event = stripe.Webhook.construct_event(payload, signature, self.webhook_secret)
            event = event.to_dict_recursive()
        except Exception as exc:
            raise BillingError("Invalid payment signature.", 400) from exc
        require(event.get("livemode") is (self.mode == "live"), "Payment mode mismatch.")
        require(event.get("api_version") == API_VERSION, "Unsupported webhook API version.")
        return event

    def validate_object(self, obj):
        require(obj.get("livemode") is (self.mode == "live"), "Payment object mode mismatch.")

    def customer(self, binding, key):
        obj = self.call("customers", "create", {"metadata": {"app": APP, "binding_ref": binding}},
                        options={"idempotency_key": key})
        self.validate_object(obj)
        require(obj.get("metadata") == {"app": APP, "binding_ref": binding})
        return obj["id"]

    def create_checkout(self, customer_id, sku, idempotency_key, purchase_ref):
        require(self.checkout_available, "Checkout is unavailable.", 503)
        recurring = sku in PLANS
        product = PLANS[sku].name if recurring else CREDIT_PACKS[sku].name
        price = {"currency": "usd", "unit_amount": amount(sku), "product_data": {"name": product}}
        if recurring:
            price["recurring"] = {"interval": "month"}
        params = {"mode": "subscription" if recurring else "payment", "customer": customer_id,
                  "line_items": [{"price_data": price, "quantity": 1}], "metadata": metadata(purchase_ref),
                  "success_url": self.origin + "/?checkout=success&session_id={CHECKOUT_SESSION_ID}",
                  "cancel_url": self.origin + "/?checkout=cancelled",
                  "subscription_data" if recurring else "payment_intent_data": {"metadata": metadata(purchase_ref)}}
        obj = self.call("checkout.sessions", "create", params, options={"idempotency_key": idempotency_key})
        self.validate_object(obj)
        require(ident(obj.get("customer")) == customer_id and obj.get("metadata") == metadata(purchase_ref))
        require(obj.get("amount_total") == amount(sku) and obj.get("currency") == "usd")
        require(obj.get("mode") == params["mode"] and obj.get("url", "").startswith("https://checkout.stripe.com/"))
        return {"session_id": obj["id"], "checkout_url": obj["url"], "provider": self.name, "mode": self.mode}

    def validate_management(self):
        require(self.portal_configuration, "Payment management is not configured.", 503)
        config = self.call("billing_portal.configurations", "retrieve", self.portal_configuration)
        self.validate_object(config)
        features = config.get('features', {})
        require(config.get('active') and features.get('payment_method_update', {}).get('enabled') is True and
                features.get('subscription_cancel', {}).get('enabled') is True and
                features['subscription_cancel'].get('mode') == 'at_period_end' and
                not features.get('subscription_update', {}).get('enabled'), "Hosted management configuration needs owner setup.", 503)


def get_provider():
    require(os.getenv("STX_BILLING_PROVIDER", "stripe") == "stripe", "Unsupported billing provider.", 503)
    return StripeBillingProvider()


def refresh_account_access(db, account_id):
    """Expiry is enforced by reads/debits, even if a webhook is delayed."""
    records = db.execute("SELECT * FROM stx_subscriptions WHERE account_id=?", (account_id,)).fetchall()
    if not records:
        return  # Preserve existing manually administered/legacy accounts.
    valid = [r for r in records if not r['terminal'] and not r['blocked'] and r['paid_through'] > time.time()]
    if valid:
        return
    paid_pack = db.execute("SELECT 1 FROM stx_credit_lots WHERE account_id=? AND revoked=0", (account_id,)).fetchone()
    db.execute("UPDATE accounts SET plan_id='free',pages_used=MAX(pages_used,3),pro=? WHERE id=?", (bool(paid_pack), account_id))


def record_spend(db, account_id, included, credits):
    if included:
        row = db.execute("SELECT c.invoice_id FROM stx_cycles c JOIN stx_subscriptions s USING(subscription_id) WHERE s.account_id=? AND s.terminal=0 AND s.blocked=0 AND c.reversed=0 AND c.period_start=s.cycle_start AND c.period_end>? ORDER BY c.period_start DESC LIMIT 1", (account_id, time.time())).fetchone()
        if row:
            db.execute("UPDATE stx_cycles SET used_pages=used_pages+? WHERE invoice_id=?", (included, row['invoice_id']))
    # FIFO purchase lots retain consumed history for safe reversals. Legacy or
    # owner-added credits have no Stripe lot and are left independently intact.
    for lot in db.execute("SELECT rowid,* FROM stx_credit_lots WHERE account_id=? AND revoked=0 AND remaining>0 ORDER BY rowid", (account_id,)).fetchall():
        take = min(credits, lot['remaining'])
        db.execute("UPDATE stx_credit_lots SET remaining=remaining-?,consumed=consumed+? WHERE purchase_ref=?", (take, take, lot['purchase_ref']))
        credits -= take
        if not credits:
            break


def _request(db, key, account_id, sku):
    alias = db.execute("SELECT * FROM checkout_aliases WHERE request_key=?", (key,)).fetchone()
    if alias:
        require((alias['account_id'], alias['sku']) == (account_id, sku), "Checkout key belongs to another request.", 409)
        key = alias['canonical_key']
    row = db.execute("SELECT * FROM checkout_requests WHERE request_key=?", (key,)).fetchone()
    if row:
        require((row['account_id'], row['sku']) == (account_id, sku), "Checkout key belongs to another request.", 409)
    return row


def create_checkout(ledger, provider, account_id, sku, request_key):
    require(sku in CREDIT_PACKS or sku in PLANS and sku != 'free', "Unknown paid SKU.")
    require(isinstance(account_id, str) and 1 <= len(account_id) <= 200, "Invalid account capability.")
    require(isinstance(request_key, str) and 16 <= len(request_key) <= 200, "Idempotency-Key must be 16 to 200 characters.")
    ledger.require_mode(provider.mode)
    # Reserve references before provider I/O. A crash cannot generate a second
    # customer/checkout key, and parallel workers serialize the second phase.
    with ledger.transaction() as db:
        ledger.ensure_account(db, account_id)
        require(not ledger.read_account(db, account_id).billing_hold, "Payment account needs owner reconciliation.", 409)
        require(not db.execute("SELECT 1 FROM stx_actions a JOIN checkout_requests r USING(purchase_ref) WHERE r.account_id=? AND a.complete=0", (account_id,)).fetchone(), "Previous subscription cancellation is pending. Retry later.", 409)
        row = _request(db, request_key, account_id, sku)
        if not row:
            pending = db.execute("SELECT * FROM checkout_requests WHERE account_id=? AND state='pending' AND app=? AND mode=? ORDER BY attempted_at DESC LIMIT 1", (account_id, APP, provider.mode)).fetchone()
            if pending:
                require(pending['sku'] == sku, "Finish the pending checkout before another purchase.", 409)
                db.execute("INSERT INTO checkout_aliases VALUES (?,?,?,?)", (request_key, pending['request_key'], account_id, sku))
                row = pending
            else:
                if sku in PLANS:
                    require(not db.execute("SELECT 1 FROM stx_subscriptions WHERE account_id=? AND terminal=0", (account_id,)).fetchone(), "Manage the existing subscription before buying another.", 409)
                    require(not db.execute("SELECT 1 FROM checkout_requests WHERE account_id=? AND sku IN ('starter','business','firm') AND state='fulfilled' AND app IS NULL", (account_id,)).fetchone(), "Legacy subscription requires owner reconciliation.", 409)
                ref = uuid.uuid4().hex
                db.execute("INSERT INTO checkout_requests(request_key,account_id,sku,attempted_at,provider_key,app,mode,purchase_ref) VALUES (?,?,?,?,?,?,?,?)", (request_key, account_id, sku, time.time(), 'stx-checkout-' + ref, APP, provider.mode, ref))
                row = _request(db, request_key, account_id, sku)
        require(row['app'] == APP and row['mode'] == provider.mode, "Legacy checkout requires owner reconciliation.", 409)
        if not db.execute("SELECT 1 FROM stx_customers WHERE account_id=? AND mode=?", (account_id, provider.mode)).fetchone():
            db.execute("INSERT INTO stx_customers(account_id,mode,binding_ref,attempted_at) VALUES (?,?,?,?)", (account_id, provider.mode, uuid.uuid4().hex, time.time()))
    with ledger.transaction() as db:
        row = _request(db, request_key, account_id, sku)
        if row['response']:
            return json.loads(row['response'])
        require(time.time() - row['attempted_at'] < 23 * 3600, "Ambiguous checkout requires owner reconciliation.", 409)
        customer = db.execute("SELECT * FROM stx_customers WHERE account_id=? AND mode=?", (account_id, provider.mode)).fetchone()
        if not customer['customer_id']:
            require(time.time() - customer['attempted_at'] < 23 * 3600, "Ambiguous customer requires owner reconciliation.", 409)
            customer_id = provider.customer(customer['binding_ref'], 'stx-customer-' + customer['binding_ref'])
            db.execute("UPDATE stx_customers SET customer_id=? WHERE binding_ref=?", (customer_id, customer['binding_ref']))
        else:
            customer_id = customer['customer_id']
        db.execute("UPDATE checkout_requests SET customer_id=? WHERE request_key=?", (customer_id, row['request_key']))
    # Customer ownership survives a process crash or ambiguous Checkout result.
    with ledger.transaction() as db:
        row = _request(db, request_key, account_id, sku)
        if row['response']:
            return json.loads(row['response'])
        require(time.time() - row['attempted_at'] < 23 * 3600, "Ambiguous checkout requires owner reconciliation.", 409)
        customer_id = row['customer_id']
        if sku in PLANS:
            provider.validate_management()
        response = provider.create_checkout(customer_id, sku, row['provider_key'], row['purchase_ref'])
        db.execute("UPDATE checkout_requests SET customer_id=?,session_id=?,response=? WHERE request_key=?", (customer_id, response['session_id'], json.dumps(response), row['request_key']))
        return response


def checkout_status(ledger, session_id, account_id):
    with ledger.transaction() as db:
        row = db.execute("SELECT * FROM checkout_requests WHERE session_id=? AND account_id=?", (session_id, account_id)).fetchone()
        require(row is not None, "Checkout not found.", 404)
        return {"session_id": row['session_id'], "sku": row['sku'], "status": row['state']}


def create_portal(ledger, provider, account_id):
    ledger.require_mode(provider.mode)
    require(provider.portal_configuration, "Payment management is not configured.", 503)
    with ledger.transaction() as db:
        binding = db.execute("SELECT * FROM stx_customers WHERE account_id=? AND mode=?", (account_id, provider.mode)).fetchone()
        require(binding and binding['customer_id'], "No owned payment customer found.", 404)
        customer = provider.call("customers", "retrieve", binding['customer_id'])
        provider.validate_object(customer)
        require(not customer.get('deleted') and customer.get('metadata') == {'app': APP, 'binding_ref': binding['binding_ref']})
        provider.validate_management()
        result = provider.call("billing_portal.sessions", "create", {'customer': binding['customer_id'], 'configuration': provider.portal_configuration, 'return_url': provider.origin + '/'})
        require(result.get('url', '').startswith('https://billing.stripe.com/'))
        return {'portal_url': result['url']}


def _owned(db, obj, provider, kind):
    """Resolve only durable references, never caller-supplied account metadata."""
    meta = obj.get('metadata') or {}
    if kind == 'invoice':
        parent = obj.get('parent') or {}
        meta = (parent.get('subscription_details') or {}).get('metadata') or {}
    ref = meta.get('purchase_ref') if meta.get('app') == APP else None
    row = db.execute("SELECT * FROM checkout_requests WHERE purchase_ref=?", (ref,)).fetchone() if ref else None
    column = 'session_id' if kind == 'checkout' else 'subscription_id' if kind == 'subscription' else None
    direct = db.execute(f"SELECT * FROM checkout_requests WHERE {column}=? AND app=?", (obj.get('id'), APP)).fetchone() if column else None
    if direct:
        require(not row or row['purchase_ref'] == direct['purchase_ref'])
        row = direct
        require(meta == metadata(row['purchase_ref']))
    if not row:
        return None
    require(row['app'] == APP and row['mode'] == provider.mode)
    provider.validate_object(obj)
    require(ident(obj.get('customer')) == row['customer_id'])
    return row


def _subscription(db, row, sub, provider):
    provider.validate_object(sub)
    require(ident(sub.get('customer')) == row['customer_id'] and sub.get('metadata') == metadata(row['purchase_ref']))
    items = (sub.get('items') or {}).get('data', [])
    require(len(items) == 1 and not sub['items'].get('has_more'))
    item = items[0]
    price = item.get('price') or {}
    require(item.get('quantity') == 1 and price.get('currency') == 'usd' and price.get('unit_amount') == amount(row['sku']) and
            (price.get('recurring') or {}).get('interval') == 'month' and (price.get('recurring') or {}).get('interval_count', 1) == 1)
    require(isinstance(item.get('current_period_start'), int) and isinstance(item.get('current_period_end'), int))
    require(item['current_period_end'] > item['current_period_start'])
    require(not row['subscription_id'] or row['subscription_id'] == sub['id'])
    existing = db.execute("SELECT terminal FROM stx_subscriptions WHERE subscription_id=?", (sub['id'],)).fetchone()
    other = not (existing and existing['terminal']) and db.execute("SELECT 1 FROM stx_subscriptions WHERE account_id=? AND terminal=0 AND subscription_id!=?", (row['account_id'], sub['id'])).fetchone()
    require(not other, "Conflicting active subscriptions require owner reconciliation.", 409)
    db.execute("INSERT OR IGNORE INTO stx_subscriptions(subscription_id,purchase_ref,account_id,customer_id,mode,sku) VALUES (?,?,?,?,?,?)", (sub['id'], row['purchase_ref'], row['account_id'], row['customer_id'], provider.mode, row['sku']))
    db.execute("UPDATE checkout_requests SET subscription_id=? WHERE purchase_ref=?", (sub['id'], row['purchase_ref']))
    return item


def _payment(db, row, pi_id, provider, invoice_id=None, subscription_id=None):
    require(isinstance(pi_id, str), "Payment evidence is incomplete.", 503)
    pi = provider.call('payment_intents', 'retrieve', pi_id)
    provider.validate_object(pi)
    require(ident(pi.get('customer')) == row['customer_id'] and pi.get('currency') == 'usd' and pi.get('amount') == amount(row['sku']))
    # Invoice-created PaymentIntents don't inherit subscription metadata. Their
    # ownership comes from the verified invoice payment association instead.
    require(invoice_id or pi.get('metadata') == metadata(row['purchase_ref']))
    require(pi.get('status') == 'succeeded' and pi.get('amount_received') == amount(row['sku']), "Payment is not fully paid.", 409)
    charge_id = ident(pi.get('latest_charge'))
    require(isinstance(charge_id, str), "Charge evidence is incomplete.", 503)
    prior = db.execute("SELECT * FROM stx_payments WHERE payment_intent=?", (pi_id,)).fetchone()
    if prior:
        require(prior['purchase_ref'] == row['purchase_ref'] and prior['invoice_id'] == invoice_id)
    else:
        db.execute("INSERT INTO stx_payments(payment_intent,purchase_ref,customer_id,mode,amount,charge_id,invoice_id,subscription_id) VALUES (?,?,?,?,?,?,?,?)", (pi_id, row['purchase_ref'], row['customer_id'], provider.mode, amount(row['sku']), charge_id, invoice_id, subscription_id))
    # A full refund/dispute may precede our paid webhook. Retrieve the charge as
    # well: old paid deliveries cannot revive reversed access.
    charge = provider.call('charges', 'retrieve', charge_id)
    provider.validate_object(charge)
    require(ident(charge.get('payment_intent')) == pi_id and ident(charge.get('customer')) == row['customer_id'] and charge.get('currency') == 'usd' and charge.get('amount') == amount(row['sku']))
    if charge.get('amount_refunded', 0) or charge.get('disputed'):
        _reverse(db, row, pi_id, bool(charge.get('disputed')), charge.get('amount_refunded', 0) != amount(row['sku']))
    return db.execute("SELECT * FROM stx_payments WHERE payment_intent=?", (pi_id,)).fetchone()


def _invoice(db, obj, row, provider):
    require(row['sku'] in PLANS and row['sku'] != 'free')
    require(obj.get('currency') == 'usd' and obj.get('amount_due') == amount(row['sku']) and obj.get('amount_paid') == amount(row['sku']) and obj.get('status') == 'paid')
    parent = obj.get('parent') or {}
    require(parent.get('type') == 'subscription_details')
    sub_id = ident(parent['subscription_details'].get('subscription'))
    sub = provider.call('subscriptions', 'retrieve', sub_id)
    item = _subscription(db, row, sub, provider)
    lines = obj.get('lines') or {}
    require(not lines.get('has_more') and len(lines.get('data', [])) == 1)
    line = lines['data'][0]
    lp = line.get('parent') or {}
    detail = lp.get('subscription_item_details') or {}
    require(lp.get('type') == 'subscription_item_details' and ident(detail.get('subscription')) == sub_id and
            ident(detail.get('subscription_item')) == item['id'] and not detail.get('proration') and
            line.get('amount') == amount(row['sku']) and line.get('quantity') == 1)
    start, end = (line.get('period') or {}).get('start'), (line.get('period') or {}).get('end')
    require(isinstance(start, int) and isinstance(end, int) and end > start)
    payments = provider.call('invoice_payments', 'list', {'invoice': obj['id'], 'limit': 100})
    require(not payments.get('has_more') and len(payments.get('data', [])) == 1, "Complex invoice requires owner reconciliation.", 409)
    payment = payments['data'][0]
    provider.validate_object(payment)
    p = payment.get('payment') or {}
    require(payment.get('status') == 'paid' and payment.get('amount_paid') == amount(row['sku']) and
            payment.get('amount_requested') == amount(row['sku']) and payment.get('currency') == 'usd' and
            ident(payment.get('invoice')) == obj['id'] and p.get('type') == 'payment_intent')
    paid = _payment(db, row, ident(p.get('payment_intent')), provider, obj['id'], sub_id)
    prior = db.execute("SELECT * FROM stx_cycles WHERE subscription_id=? AND period_start=?", (sub_id, start)).fetchone()
    if prior:
        require(prior['invoice_id'] == obj['id'] and prior['period_end'] == end)
    else:
        db.execute("INSERT INTO stx_cycles(invoice_id,subscription_id,period_start,period_end,amount,reversed) VALUES (?,?,?,?,?,?)", (obj['id'], sub_id, start, end, amount(row['sku']), int(bool(paid['reversed'] or paid['disputed']))))
    state = db.execute("SELECT * FROM stx_subscriptions WHERE subscription_id=?", (sub_id,)).fetchone()
    # Active is never payment evidence; both a paid invoice and the current
    # service period must match. Stale cycles are recorded but cannot reset use.
    if not state['terminal'] and not paid['reversed'] and not paid['disputed'] and start > state['cycle_start'] and end > time.time() and sub.get('status') in {'active', 'past_due'} and item['current_period_start'] == start and item['current_period_end'] == end:
        db.execute("UPDATE stx_subscriptions SET cycle_start=?,paid_through=?,blocked=0,status=?,cancel_at_period_end=? WHERE subscription_id=?", (start, end, sub['status'], bool(sub.get('cancel_at_period_end')), sub_id))
        db.execute("UPDATE accounts SET plan_id=?,pages_used=0,pro=1 WHERE id=?", (row['sku'], row['account_id']))
        db.execute('UPDATE stx_cycles SET granted=1 WHERE invoice_id=?', (obj['id'],))
    elif not state['terminal'] and not paid['reversed'] and not paid['disputed'] and start > state['cycle_start'] and end > time.time() and start >= item['current_period_start']:
        # Paid invoice can precede subscription propagation. Ask Stripe to retry
        # rather than acknowledge payment and permanently lose its allowance.
        raise BillingError('Paid cycle is awaiting provider confirmation. Retry later.')
    granted = db.execute('SELECT granted FROM stx_cycles WHERE invoice_id=?', (obj['id'],)).fetchone()[0]
    if granted and not state['terminal'] and not paid['reversed'] and not paid['disputed']:
        db.execute("UPDATE checkout_requests SET state=CASE WHEN state='pending' THEN 'fulfilled' ELSE state END WHERE purchase_ref=?", (row['purchase_ref'],))
        # Use the durable purchase ref even when invoice arrives before Checkout.
        db.execute("INSERT OR IGNORE INTO entitlements VALUES (?,?,?)", ('purchase:' + row['purchase_ref'], row['account_id'], row['sku']))


def _reverse(db, row, pi_id, disputed, ambiguous=False):
    payment = db.execute("SELECT * FROM stx_payments WHERE payment_intent=?", (pi_id,)).fetchone()
    require(payment and payment['purchase_ref'] == row['purchase_ref'])
    if payment['reversed'] and (not disputed or payment['disputed']):
        return  # Later deliveries never re-open an owner-resolved hold.
    db.execute("UPDATE stx_payments SET reversed=1,disputed=MAX(disputed,?) WHERE payment_intent=?", (disputed, pi_id))
    consumed = False
    cancellation_pending = False
    if row['sku'] in CREDIT_PACKS:
        lot = db.execute("SELECT * FROM stx_credit_lots WHERE purchase_ref=?", (row['purchase_ref'],)).fetchone()
        if lot:
            consumed = bool(lot['consumed'])
            if not lot['revoked']:
                db.execute("UPDATE accounts SET credits=credits-? WHERE id=?", (lot['remaining'], row['account_id']))
                db.execute("UPDATE stx_credit_lots SET remaining=0,revoked=1 WHERE purchase_ref=?", (row['purchase_ref'],))
    else:
        cycle = db.execute("SELECT * FROM stx_cycles WHERE invoice_id=?", (payment['invoice_id'],)).fetchone()
        consumed = bool(cycle and cycle['used_pages'])
        db.execute("UPDATE stx_cycles SET reversed=1 WHERE invoice_id=?", (payment['invoice_id'],))
        db.execute("UPDATE stx_subscriptions SET terminal=1,blocked=1 WHERE purchase_ref=?", (row['purchase_ref'],))
        # Refunds don't cancel Stripe subscriptions. Persist the required stop
        # before provider I/O, so a crash cannot leave automatic renewal running.
        db.execute("INSERT OR IGNORE INTO stx_actions(subscription_id,purchase_ref,mode) VALUES (?,?,?)", (payment['subscription_id'], row['purchase_ref'], row['mode']))
        cancellation_pending = not db.execute('SELECT complete FROM stx_actions WHERE subscription_id=?', (payment['subscription_id'],)).fetchone()[0]
    db.execute("UPDATE checkout_requests SET state='reversed' WHERE purchase_ref=?", (row['purchase_ref'],))
    if consumed or disputed or ambiguous or cancellation_pending:
        reason = 'reversal_needs_reconciliation' if consumed or disputed or ambiguous else 'provider_cancellation_pending'
        db.execute("INSERT INTO stx_holds(purchase_ref,account_id,reason) VALUES (?,?,?) ON CONFLICT(purchase_ref) DO UPDATE SET resolved=0,reason=CASE WHEN excluded.reason='reversal_needs_reconciliation' THEN excluded.reason ELSE stx_holds.reason END", (row['purchase_ref'], row['account_id'], reason))
    refresh_account_access(db, row['account_id'])
    if row['sku'] in CREDIT_PACKS:
        active = db.execute("SELECT 1 FROM stx_subscriptions WHERE account_id=? AND terminal=0 AND blocked=0 AND paid_through>?", (row['account_id'], time.time())).fetchone()
        pack = db.execute("SELECT 1 FROM stx_credit_lots WHERE account_id=? AND revoked=0", (row['account_id'],)).fetchone()
        db.execute("UPDATE accounts SET pro=? WHERE id=?", (bool(active or pack), row['account_id']))


def resolve_hold(ledger, purchase_ref):
    """Trusted owner operation after reconciliation; never restores a purchase.

    No public endpoint: access to the durable database is the authority. History,
    revoked lots, terminal subscription and idempotency markers stay intact.
    """
    with ledger.transaction() as db:
        require(not db.execute("SELECT 1 FROM stx_actions WHERE purchase_ref=? AND complete=0", (purchase_ref,)).fetchone(), "Provider cancellation must be confirmed before resolving this hold.", 409)
        require(db.execute("SELECT 1 FROM stx_holds WHERE purchase_ref=?", (purchase_ref,)).fetchone(), "Hold not found.", 404)
        db.execute("UPDATE stx_holds SET resolved=1 WHERE purchase_ref=?", (purchase_ref,))


def _reversal_row(db, obj, provider, dispute):
    pi_id = ident(obj.get('payment_intent'))
    charge = provider.call('charges', 'retrieve', ident(obj.get('charge'))) if dispute else obj
    provider.validate_object(charge)
    pi_id = pi_id or ident(charge.get('payment_intent'))
    known = db.execute("SELECT * FROM stx_payments WHERE payment_intent=? OR charge_id=?", (pi_id, charge.get('id'))).fetchone()
    row = db.execute("SELECT * FROM checkout_requests WHERE purchase_ref=?", (known['purchase_ref'],)).fetchone() if known else _owned(db, charge, provider, 'charge')
    if not row:
        # Invoice PaymentIntents don't have app metadata. Only inspect an invoice
        # for an already bound app customer; shared-account foreign traffic is inert.
        binding = db.execute("SELECT 1 FROM stx_customers WHERE customer_id=? AND mode=?", (ident(charge.get('customer')), provider.mode)).fetchone()
        if not binding:
            return None, None, None
        require(isinstance(pi_id, str) and ident(charge.get('payment_intent')) == pi_id)
        found = provider.call('invoice_payments', 'list', {'payment': {'type': 'payment_intent', 'payment_intent': pi_id}, 'limit': 100})
        require(not found.get('has_more'), "Payment ownership needs reconciliation.", 503)
        for p in found.get('data', []):
            inv = provider.call('invoices', 'retrieve', ident(p.get('invoice')))
            candidate = _owned(db, inv, provider, 'invoice')
            if candidate:
                provider.validate_object(p)
                require(p.get('currency') == 'usd' and p.get('status') == 'paid' and
                        p.get('amount_paid') == amount(candidate['sku']) and p.get('amount_requested') == amount(candidate['sku']) and
                        (p.get('payment') or {}).get('type') == 'payment_intent' and
                        ident(p['payment'].get('payment_intent')) == pi_id and ident(p.get('invoice')) == inv.get('id'))
                require(row is None, "Ambiguous payment ownership.", 409)
                row = candidate
                sub_id = ident(inv['parent']['subscription_details']['subscription'])
                sub = provider.call('subscriptions', 'retrieve', sub_id)
                _subscription(db, row, sub, provider)
                db.execute("INSERT OR IGNORE INTO stx_payments(payment_intent,purchase_ref,customer_id,mode,amount,charge_id,invoice_id,subscription_id) VALUES (?,?,?,?,?,?,?,?)", (pi_id, row['purchase_ref'], row['customer_id'], provider.mode, amount(row['sku']), charge['id'], inv['id'], sub_id))
        if not row:
            return None, None, None
    require(ident(charge.get('customer')) == row['customer_id'] and charge.get('currency') == 'usd' and charge.get('amount') == amount(row['sku']))
    require(isinstance(pi_id, str) and ident(charge.get('payment_intent')) == pi_id)
    if row['sku'] in CREDIT_PACKS:
        require(charge.get('metadata') == metadata(row['purchase_ref']))
    require(not known or known['charge_id'] == charge['id'])
    if not known and row['sku'] in CREDIT_PACKS:
        require(charge.get('metadata') == metadata(row['purchase_ref']))
        db.execute("INSERT OR IGNORE INTO stx_payments(payment_intent,purchase_ref,customer_id,mode,amount,charge_id) VALUES (?,?,?,?,?,?)", (pi_id, row['purchase_ref'], row['customer_id'], provider.mode, amount(row['sku']), charge['id']))
    if dispute:
        require(obj.get('currency') == 'usd' and 0 < obj.get('amount', 0) <= amount(row['sku']) and ident(obj.get('charge')) == charge['id'])
    return row, pi_id, charge


def _apply_webhook(ledger, event, provider):
    provider = provider or get_provider()
    ledger.require_mode(provider.mode)
    require(event.get('livemode') is (provider.mode == 'live'), "Payment mode mismatch.")
    require(event.get('api_version') == API_VERSION, "Unsupported webhook API version.")
    require(isinstance(event.get('id'), str) and isinstance(event.get('type'), str), "Invalid event.")
    kind = event['type']
    if kind not in EVENTS:
        return {'received': True, 'ignored': True, 'granted': False}
    obj = (event.get('data') or {}).get('object') or {}
    provider.validate_object(obj)
    with ledger.transaction() as db:
        before_grants = db.execute("SELECT COUNT(*) FROM entitlements").fetchone()[0]
        if db.execute("SELECT 1 FROM webhook_events WHERE event_id=?", (event['id'],)).fetchone():
            return {'received': True, 'duplicate': True, 'granted': False}
        if kind.startswith('charge.'):
            row, pi_id, charge = _reversal_row(db, obj, provider, 'dispute' in kind)
            if not row:
                return {'received': True, 'ignored': True, 'granted': False}
            if kind == 'charge.refunded':
                require(0 < charge.get('amount_refunded', 0) <= amount(row['sku']))
            _reverse(db, row, pi_id, 'dispute' in kind, charge.get('amount_refunded', 0) != amount(row['sku']) and kind == 'charge.refunded')
        else:
            family = 'checkout' if kind.startswith('checkout.') else 'invoice' if kind.startswith('invoice.') else 'subscription'
            row = _owned(db, obj, provider, family)
            if not row:
                return {'received': True, 'ignored': True, 'granted': False}
            ledger.ensure_account(db, row['account_id'])
            if family == 'checkout':
                require(obj.get('amount_total') == amount(row['sku']) and obj.get('currency') == 'usd' and obj.get('mode') == ('payment' if row['sku'] in CREDIT_PACKS else 'subscription'))
                require(not row['session_id'] or row['session_id'] == obj['id'])
                db.execute("UPDATE checkout_requests SET session_id=COALESCE(session_id,?) WHERE purchase_ref=?", (obj['id'], row['purchase_ref']))
                if kind.endswith(('expired', 'async_payment_failed')):
                    db.execute("UPDATE checkout_requests SET state=? WHERE purchase_ref=? AND state='pending'", ('expired' if kind.endswith('expired') else 'cancelled', row['purchase_ref']))
                elif obj.get('payment_status') == 'paid':
                    if row['sku'] in CREDIT_PACKS:
                        paid = _payment(db, row, ident(obj.get('payment_intent')), provider)
                        if not paid['reversed'] and not paid['disputed'] and row['state'] not in {'reversed', 'fulfilled'}:
                            granted = db.execute("INSERT OR IGNORE INTO stx_credit_lots(purchase_ref,account_id,granted,remaining) VALUES (?,?,?,?)", (row['purchase_ref'], row['account_id'], CREDIT_PACKS[row['sku']].credits, CREDIT_PACKS[row['sku']].credits)).rowcount
                            if granted:
                                db.execute("UPDATE accounts SET credits=credits+?,pro=1 WHERE id=?", (CREDIT_PACKS[row['sku']].credits, row['account_id']))
                            db.execute("UPDATE checkout_requests SET state='fulfilled' WHERE purchase_ref=?", (row['purchase_ref'],))
                            db.execute("INSERT OR IGNORE INTO entitlements VALUES (?,?,?)", (obj['id'], row['account_id'], row['sku']))
                    else:
                        inv = provider.call('invoices', 'retrieve', ident(obj.get('invoice')))
                        require(_owned(db, inv, provider, 'invoice') is not None)
                        require(ident(obj.get('subscription')) == ident(inv['parent']['subscription_details']['subscription']))
                        _invoice(db, inv, row, provider)
            elif family == 'invoice':
                if kind == 'invoice.paid':
                    _invoice(db, obj, row, provider)
                else:
                    # A failed invoice never revokes an already-paid period or
                    # grants grace beyond paid_through. New paid evidence recovers.
                    sub_id = ident((obj.get('parent') or {}).get('subscription_details', {}).get('subscription'))
                    sub = provider.call('subscriptions', 'retrieve', sub_id)
                    _subscription(db, row, sub, provider)
                    refresh_account_access(db, row['account_id'])
            else:
                # Retrieve current state so delivery order/second-level event
                # timestamps cannot undo a later cancellation or unpaid expiry.
                sub = obj if kind.endswith('deleted') else provider.call('subscriptions', 'retrieve', obj['id'])
                _subscription(db, row, sub, provider)
                terminal = kind.endswith('deleted') or sub.get('status') in {'canceled', 'incomplete_expired'}
                blocked = sub.get('status') in {'unpaid', 'paused'}
                db.execute("UPDATE stx_subscriptions SET terminal=MAX(terminal,?),blocked=MAX(blocked,?),cancel_at_period_end=?,status=? WHERE subscription_id=?", (terminal, blocked, bool(sub.get('cancel_at_period_end')), sub.get('status', 'unknown'), sub['id']))
                if terminal:
                    db.execute("UPDATE checkout_requests SET state='cancelled' WHERE purchase_ref=? AND state='pending'", (row['purchase_ref'],))
                refresh_account_access(db, row['account_id'])
        db.execute("INSERT INTO webhook_events VALUES (?)", (event['id'],))
        return {'received': True, 'granted': db.execute("SELECT COUNT(*) FROM entitlements").fetchone()[0] > before_grants}


def drain_actions(ledger, provider, limit=4):
    """Bounded durable outbox, safe across workers, crashes and provider failure.

    DELETE cancellation is retried by verified resource state, not by assuming
    Stripe's POST idempotency retention. No provider I/O holds a SQLite lock.
    """
    ledger.require_mode(provider.mode)
    completed = 0
    for _ in range(limit):
        with ledger.transaction() as db:
            action = db.execute("SELECT * FROM stx_actions WHERE complete=0 AND next_attempt<=? AND mode=? ORDER BY next_attempt LIMIT 1", (time.time(), provider.mode)).fetchone()
            if not action:
                break
            db.execute("UPDATE stx_actions SET next_attempt=?,attempts=attempts+1 WHERE subscription_id=?", (time.time() + 60, action['subscription_id']))
            row = db.execute("SELECT * FROM checkout_requests WHERE purchase_ref=?", (action['purchase_ref'],)).fetchone()
            binding = db.execute("SELECT * FROM stx_customers WHERE customer_id=? AND mode=?", (row['customer_id'], provider.mode)).fetchone() if row else None
        try:
            require(row and binding and row['app'] == APP and row['mode'] == provider.mode and row['subscription_id'] == action['subscription_id'])
            customer = provider.call('customers', 'retrieve', row['customer_id'])
            provider.validate_object(customer)
            require(not customer.get('deleted') and customer.get('metadata') == {'app': APP, 'binding_ref': binding['binding_ref']})
            sub = provider.call('subscriptions', 'retrieve', action['subscription_id'])
            def validate(sub):
                provider.validate_object(sub)
                require(sub.get('id') == action['subscription_id'] and ident(sub.get('customer')) == row['customer_id'] and sub.get('metadata') == metadata(row['purchase_ref']))
            validate(sub)
            if sub.get('status') != 'canceled':
                sub = provider.call('subscriptions', 'cancel', action['subscription_id'], {'invoice_now': False, 'prorate': False})
                validate(sub)
            require(sub.get('status') == 'canceled', "Subscription cancellation is not confirmed.", 503)
        except Exception:
            with ledger.transaction() as db:
                db.execute("UPDATE stx_actions SET next_attempt=?,last_error='confirmation_pending' WHERE subscription_id=? AND complete=0", (time.time() + min(300, 5 * 2 ** min(action['attempts'], 6)), action['subscription_id']))
        else:
            with ledger.transaction() as db:
                db.execute("UPDATE stx_actions SET complete=1,next_attempt=0,last_error=NULL WHERE subscription_id=?", (action['subscription_id'],))
                db.execute("UPDATE stx_subscriptions SET status='canceled',terminal=1,blocked=1 WHERE subscription_id=?", (action['subscription_id'],))
                db.execute("UPDATE stx_holds SET resolved=1 WHERE purchase_ref=? AND reason='provider_cancellation_pending'", (row['purchase_ref'],))
                refresh_account_access(db, row['account_id'])
            completed += 1
    return {'completed': completed}


def apply_webhook(ledger, event, provider=None):
    provider = provider or get_provider()
    result = _apply_webhook(ledger, event, provider)
    if not result.get('ignored'):
        drain_actions(ledger, provider, limit=1)
    return result
