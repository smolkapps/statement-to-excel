"""Synthetic modern Stripe objects, actual signature verifier and SQLite races.

No provider requests. Doubles preserve the 2026-02-25.clover object nesting.
"""
import copy
import hashlib
import hmac
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
import statement_to_excel.api as api
from statement_to_excel.billing import BillingError, PersistentLedger, StripeBillingProvider, apply_webhook, create_checkout
from statement_to_excel.payments import API_VERSION, APP, amount, create_portal, resolve_hold

SECRET = 'whsec_synthetic_not_a_credential'
PURCHASES = {}


class PaymentDouble(StripeBillingProvider):
    def __init__(self, mode='test'):
        super().__init__('sk_' + mode + '_synthetic_not_a_credential', SECRET, mode=mode,
                         portal_configuration='bpc_synthetic', client=object())
        self.objects = {}
        self.sessions = {}
        self.customers = {}
        self.calls = []
        self.requests = []
        self.fail_after_creation = False
        self.lock = threading.Lock()

    def call(self, resource, method, *args, **kwargs):
        with self.lock:
            self.requests.append((resource, method, copy.deepcopy(args), copy.deepcopy(kwargs)))
            live = self.mode == 'live'
            if resource == 'customers' and method == 'create':
                key = kwargs['options']['idempotency_key']
                obj = self.customers.setdefault(key, {'id': 'cus_' + uuid.uuid4().hex, 'livemode': live, **args[0]})
                self.objects[obj['id']] = obj
            elif resource == 'checkout.sessions' and method == 'create':
                key = kwargs['options']['idempotency_key']
                self.calls.append(key)
                p = args[0]
                obj = self.sessions.setdefault(key, {'id': 'cs_' + self.mode + '_' + uuid.uuid4().hex,
                    'url': 'https://checkout.stripe.com/synthetic-only', 'livemode': live,
                    'amount_total': p['line_items'][0]['price_data']['unit_amount'], 'currency': 'usd',
                    'mode': p['mode'], 'customer': p['customer'], 'metadata': p['metadata'], 'payment_status': 'unpaid', 'status': 'open'})
                self.objects[obj['id']] = obj
                PURCHASES[obj['id']] = self
                if self.fail_after_creation:
                    self.fail_after_creation = False
                    raise BillingError('Synthetic ambiguous timeout.')
            elif resource == 'checkout.sessions' and method == 'expire':
                obj = self.objects[args[0]]
                if obj['status'] != 'open':
                    raise BillingError('Synthetic Session is no longer open.')
                obj['status'] = 'expired'
                payment = self.objects.get(obj.get('payment_intent'))
                if payment and payment['status'] in {'requires_payment_method', 'requires_confirmation', 'requires_action'}:
                    payment['status'] = 'canceled'
            elif resource == 'invoice_payments' and method == 'list':
                params = args[0]
                entries = [o for o in self.objects.values() if o.get('object') == 'invoice_payment']
                if 'invoice' in params:
                    entries = [p for p in entries if p['invoice'] == params['invoice']]
                else:
                    entries = [p for p in entries if p['payment']['payment_intent'] == params['payment']['payment_intent']]
                obj = {'data': entries, 'has_more': False}
            elif resource == 'billing_portal.sessions':
                obj = {'url': 'https://billing.stripe.com/synthetic-only'}
            elif resource == 'billing_portal.configurations':
                obj = self.objects.get('bpc_synthetic', {'id': 'bpc_synthetic', 'livemode': live, 'active': True,
                    'features': {'payment_method_update': {'enabled': True}, 'subscription_cancel': {'enabled': True, 'mode': 'at_period_end'}, 'subscription_update': {'enabled': False}}})
            elif resource == 'subscriptions' and method == 'cancel':
                assert args[1] == {'invoice_now': False, 'prorate': False}
                obj = self.objects[args[0]]
                obj['status'] = 'canceled'
                obj['ended_at'] = int(time.time())
            else:
                obj = self.objects[args[0]]
            return copy.deepcopy(obj)

    def paid(self, sid, start=None):
        obj = self.objects[sid]
        obj['payment_status'] = 'paid'
        obj['status'] = 'complete'
        ref = obj['metadata']['purchase_ref']
        pi_id, ch_id = 'pi_' + uuid.uuid4().hex, 'ch_' + uuid.uuid4().hex
        pi = {'id': pi_id, 'livemode': self.mode == 'live', 'customer': obj['customer'], 'currency': 'usd', 'amount': obj['amount_total'], 'amount_received': obj['amount_total'], 'status': 'succeeded', 'latest_charge': ch_id, 'metadata': obj['metadata'] if obj['mode'] == 'payment' else {}}
        ch = {'id': ch_id, 'livemode': self.mode == 'live', 'customer': obj['customer'], 'currency': 'usd', 'amount': obj['amount_total'], 'amount_refunded': 0, 'refunded': False, 'disputed': False, 'payment_intent': pi_id, 'metadata': pi['metadata']}
        self.objects[pi_id], self.objects[ch_id] = pi, ch
        if obj['mode'] == 'payment':
            obj['payment_intent'] = pi_id
        else:
            sub_id = obj.get('subscription') or 'sub_' + ref
            start = start or int(time.time()) - 100
            end = start + 30 * 86400
            item_id = 'si_' + ref
            self.objects[sub_id] = {'id': sub_id, 'livemode': self.mode == 'live', 'customer': obj['customer'], 'metadata': obj['metadata'], 'status': 'active', 'cancel_at_period_end': False, 'items': {'has_more': False, 'data': [{'id': item_id, 'quantity': 1, 'current_period_start': start, 'current_period_end': end, 'price': {'unit_amount': obj['amount_total'], 'currency': 'usd', 'recurring': {'interval': 'month', 'interval_count': 1}}}]}}
            inv_id = 'in_' + uuid.uuid4().hex
            self.objects[inv_id] = {'id': inv_id, 'livemode': self.mode == 'live', 'customer': obj['customer'], 'currency': 'usd', 'amount_due': obj['amount_total'], 'amount_paid': obj['amount_total'], 'status': 'paid', 'status_transitions': {'paid_at': int(time.time()) - 2}, 'parent': {'type': 'subscription_details', 'subscription_details': {'subscription': sub_id, 'metadata': obj['metadata']}}, 'lines': {'has_more': False, 'data': [{'amount': obj['amount_total'], 'quantity': 1, 'period': {'start': start, 'end': end}, 'parent': {'type': 'subscription_item_details', 'subscription_item_details': {'subscription': sub_id, 'subscription_item': item_id, 'proration': False}}}]}}
            pay_id = 'inpay_' + uuid.uuid4().hex
            self.objects[pay_id] = {'id': pay_id, 'object': 'invoice_payment', 'livemode': self.mode == 'live', 'currency': 'usd', 'invoice': inv_id, 'amount_requested': obj['amount_total'], 'amount_paid': obj['amount_total'], 'status': 'paid', 'payment': {'type': 'payment_intent', 'payment_intent': pi_id}}
            obj['subscription'], obj['invoice'] = sub_id, inv_id
            self.objects[sub_id]['latest_invoice'] = inv_id
        return copy.deepcopy(obj)


def sign(payload, secret=SECRET, timestamp=None):
    stamp = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(secret.encode(), str(stamp).encode() + b'.' + payload, hashlib.sha256).hexdigest()
    return f't={stamp},v1={digest}'


def event(obj, kind='checkout.session.completed', event_id=None):
    return {'id': event_id or 'evt_' + uuid.uuid4().hex, 'type': kind, 'created': int(time.time()), 'livemode': obj['livemode'], 'api_version': API_VERSION, 'data': {'object': copy.deepcopy(obj)}}


def buy(ledger, provider, sku='pack_50', key='purchase-request-000000001', account='buyer'):
    return create_checkout(ledger, provider, account, sku, key)


def paid_event(session_id, sku='pack_50', event_id='evt_synthetic_001', account='buyer'):
    p = PURCHASES[session_id]
    obj = p.objects[session_id]
    if obj['payment_status'] != 'paid':
        obj = p.paid(session_id)
    return event(obj, event_id=event_id)


@pytest.fixture
def ledger(tmp_path):
    return PersistentLedger(str(tmp_path / 'billing.sqlite3'))


@pytest.fixture
def provider():
    return PaymentDouble()


def grant(ledger, p, sku='pack_50', key=None, account='buyer'):
    sid = buy(ledger, p, sku, key or str(uuid.uuid4()), account)['session_id']
    ev = paid_event(sid, event_id='evt_' + uuid.uuid4().hex)
    apply_webhook(ledger, ev, p)
    return p.objects[sid]


@pytest.mark.parametrize('mode', ['test', 'live'])
@pytest.mark.parametrize('sku', ['starter', 'business', 'firm', 'pack_50', 'pack_200', 'pack_1000'])
def test_full_catalog_mode_server_prices_quantities_and_paid_grants(tmp_path, mode, sku):
    p = PaymentDouble(mode)
    ledger = PersistentLedger(str(tmp_path / 'billing.sqlite3'), mode=mode)
    sid = buy(ledger, p, sku)['session_id']
    checkout = next(r[2][0] for r in p.requests if r[:2] == ('checkout.sessions', 'create'))
    assert checkout['line_items'][0]['quantity'] == 1
    assert checkout['line_items'][0]['price_data']['unit_amount'] == amount(sku)
    assert checkout['line_items'][0]['price_data']['currency'] == 'usd'
    assert checkout['customer'].startswith('cus_') and 'client_reference_id' not in checkout
    assert 'buyer' not in json.dumps(checkout)
    assert not ledger.get_or_create('buyer').pro
    ev = paid_event(sid)
    assert apply_webhook(ledger, ev, p)['granted']
    assert not apply_webhook(PersistentLedger(ledger.database_path, mode), ev, p)['granted']
    acct = ledger.get_or_create('buyer')
    if sku.startswith('pack'):
        from statement_to_excel.billing import CREDIT_PACKS
        assert acct.credits == CREDIT_PACKS[sku].credits
    else:
        assert acct.plan_id == sku and acct.pages_used_this_cycle == 0
    assert acct.pro


def test_concurrent_checkout_restart_alias_and_ambiguous_failure(ledger, provider):
    provider.fail_after_creation = True
    with pytest.raises(BillingError): buy(ledger, provider)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda i: buy(PersistentLedger(ledger.database_path), provider, key='another-checkout-key-' + str(i)), range(8)))
    assert len({r['session_id'] for r in results}) == len(provider.sessions) == len(provider.customers) == 1
    assert len(set(provider.calls)) == 1
    assert buy(ledger, provider) == results[0]


def test_ambiguous_checkout_retention_and_conflicting_keys_fail_closed(ledger, provider):
    provider.fail_after_creation = True
    with pytest.raises(BillingError): buy(ledger, provider)
    with ledger.transaction() as db: db.execute('UPDATE checkout_requests SET attempted_at=?', (time.time() - 86400,))
    with pytest.raises(BillingError, match='reconciliation'): buy(ledger, provider)
    with pytest.raises(BillingError): buy(ledger, provider, account='different')
    assert len(provider.calls) == 1


def test_concurrent_plans_and_active_subscription_guard(ledger, provider):
    def invoke(sku):
        try: return buy(ledger, provider, sku, key='request-plan-key-' + sku)
        except BillingError as exc: return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool: result = list(pool.map(invoke, ['starter', 'business']))
    assert any(isinstance(r, dict) for r in result)
    # Choice changes may serialize as a confirmed expiry then a replacement;
    # only one provider Session can remain payable.
    open_sessions = [s for s in provider.sessions.values() if s['status'] == 'open']
    assert len(open_sessions) == 1
    sid = open_sessions[0]['id']
    apply_webhook(ledger, paid_event(sid), provider)
    with pytest.raises(BillingError, match='existing subscription'): buy(ledger, provider, 'firm', key='new-plan-key-000000000')


@pytest.mark.parametrize('mutation', ['event_mode', 'object_mode', 'version', 'amount', 'currency', 'customer', 'ref', 'sku_mode'])
def test_conflicting_owned_events_fail_closed(ledger, provider, mutation):
    ev = paid_event(buy(ledger, provider)['session_id'])
    obj = ev['data']['object']
    if mutation == 'event_mode': ev['livemode'] = True
    if mutation == 'object_mode': obj['livemode'] = True
    if mutation == 'version': ev['api_version'] = 'old-version'
    if mutation == 'amount': obj['amount_total'] = 1
    if mutation == 'currency': obj['currency'] = 'eur'
    if mutation == 'customer': obj['customer'] = 'cus_foreign'
    if mutation == 'ref': obj['metadata']['purchase_ref'] = 'foreign'
    if mutation == 'sku_mode': obj['mode'] = 'subscription'
    with pytest.raises(BillingError): apply_webhook(ledger, ev, provider)
    assert not ledger.get_or_create('buyer').pro
    with ledger.transaction() as db: assert not db.execute('SELECT 1 FROM webhook_events').fetchone()


@pytest.mark.parametrize('kind', ['checkout.session.completed', 'invoice.paid', 'customer.subscription.updated', 'customer.subscription.deleted', 'charge.refunded', 'charge.dispute.created'])
def test_foreign_shared_account_events_acknowledged_without_any_ledger_mutation(ledger, provider, kind):
    obj = {'id': 'foreign', 'customer': 'cus_foreign', 'livemode': False, 'metadata': {'account_id': 'buyer', 'app': 'other-app'}, 'charge': 'ch_foreign', 'payment_intent': 'pi_foreign'}
    provider.objects['ch_foreign'] = obj
    with ledger.transaction() as db:
        before = [tuple(r) for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert apply_webhook(ledger, event(obj, kind), provider)['ignored']
    with ledger.transaction() as db:
        for (table,) in before:
            if table != 'stx_settings': assert db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0


def test_real_signature_verifier_private_status_and_portal_customer_binding(ledger, provider, monkeypatch):
    sid = buy(ledger, provider)['session_id']
    monkeypatch.setattr(api, 'LEDGER', ledger); monkeypatch.setattr(api, 'PROVIDER', provider)
    payload = json.dumps(paid_event(sid)).encode()
    with TestClient(api.app) as c:
        assert c.post('/api/stripe/webhook', content=payload).status_code == 400
        assert c.post('/api/stripe/webhook', content=payload, headers={'Stripe-Signature': sign(payload, timestamp=int(time.time()) - 600)}).status_code == 400
        assert c.post('/api/stripe/webhook', content=payload, headers={'Stripe-Signature': sign(payload)}).json()['granted']
        assert not c.post('/api/stripe/webhook', content=payload, headers={'Stripe-Signature': sign(payload)}).json()['granted']
        assert c.post('/api/checkout/status', json={'account_id': 'foreign', 'session_id': sid}).status_code == 404
        assert c.post('/api/billing/portal', json={'account_id': 'foreign', 'customer_id': provider.objects[sid]['customer']}).status_code == 422
        assert c.post('/api/billing/portal', json={'account_id': 'foreign'}).status_code == 404
        assert c.post('/api/billing/portal', json={'account_id': 'buyer', 'customer_id': 'cus_foreign'}).status_code == 422
        assert c.post('/api/billing/portal', json={'account_id': 'buyer'}).status_code == 200
        params = [r[2][0] for r in provider.requests if r[:2] == ('billing_portal.sessions', 'create')][-1]
        assert params['customer'] == provider.objects[sid]['customer'] and params['return_url'] == provider.origin + '/'
        provider.objects[params['customer']]['metadata']['app'] = 'other-app'
        assert c.post('/api/billing/portal', json={'account_id': 'buyer'}).status_code == 400


def test_invoice_before_checkout_renewal_duplicates_old_cycles_and_restart(ledger, provider):
    sid = buy(ledger, provider, 'business')['session_id']; first = provider.paid(sid)
    initial = event(provider.objects[first['invoice']], 'invoice.paid')
    apply_webhook(ledger, initial, provider)
    ledger.charge_pages('buyer', 10)
    apply_webhook(ledger, paid_event(sid), provider)
    apply_webhook(ledger, initial, provider)
    assert ledger.get_or_create('buyer').pages_used_this_cycle == 10
    start = provider.objects[first['subscription']]['items']['data'][0]['current_period_start'] + 1000
    renewal = provider.paid(sid, start)
    newer = event(provider.objects[renewal['invoice']], 'invoice.paid')
    apply_webhook(PersistentLedger(ledger.database_path), newer, provider)
    ledger.charge_pages('buyer', 2)
    apply_webhook(ledger, event(initial['data']['object'], 'invoice.paid'), provider)
    apply_webhook(ledger, event(newer['data']['object'], 'invoice.paid'), provider)
    assert ledger.get_or_create('buyer').pages_used_this_cycle == 2


@pytest.mark.parametrize('terminal', ['deleted', 'canceled', 'incomplete_expired'])
def test_terminal_cancellation_and_late_paid_or_active_never_revive_preserves_packs(ledger, provider, terminal):
    grant(ledger, provider)
    obj = grant(ledger, provider, 'starter')
    sub = provider.objects[obj['subscription']]
    sub['status'] = 'canceled' if terminal == 'deleted' else terminal
    apply_webhook(ledger, event(sub, 'customer.subscription.deleted' if terminal == 'deleted' else 'customer.subscription.updated'), provider)
    sub['status'] = 'active'
    apply_webhook(ledger, event(sub, 'customer.subscription.updated'), provider)
    apply_webhook(ledger, event(obj), provider)
    acct = PersistentLedger(ledger.database_path).get_or_create('buyer')
    assert acct.plan_id == 'free' and acct.credits == 50 and acct.pro


def test_period_end_failure_expiry_and_paid_recovery_needs_newer_invoice(ledger, provider, monkeypatch):
    obj = grant(ledger, provider, 'starter')
    sub = provider.objects[obj['subscription']]
    sub['cancel_at_period_end'] = True
    apply_webhook(ledger, event(sub, 'customer.subscription.updated'), provider)
    assert ledger.get_or_create('buyer').plan_id == 'starter'
    sub['status'] = 'past_due'
    apply_webhook(ledger, event(provider.objects[obj['invoice']], 'invoice.payment_failed'), provider)
    assert ledger.get_or_create('buyer').plan_id == 'starter'
    end = sub['items']['data'][0]['current_period_end']
    import statement_to_excel.payments as payments
    monkeypatch.setattr(payments.time, 'time', lambda: end + 1)
    acct = ledger.get_or_create('buyer')
    assert acct.plan_id == 'free' and acct.included_remaining() == 0
    sub['status'] = 'active'
    apply_webhook(ledger, event(sub, 'customer.subscription.updated'), provider)
    assert ledger.get_or_create('buyer').plan_id == 'free'
    renewed = provider.paid(obj['id'], start=end)
    apply_webhook(ledger, event(provider.objects[renewed['invoice']], 'invoice.paid'), provider)
    assert ledger.get_or_create('buyer').plan_id == 'starter'


@pytest.mark.parametrize('sku', ['pack_50', 'starter'])
@pytest.mark.parametrize('reversal', ['refund', 'dispute'])
@pytest.mark.parametrize('consumed', [False, True])
def test_reversals_atomic_idempotent_non_revival_and_preserved_other_packs(ledger, provider, sku, reversal, consumed):
    grant(ledger, provider, 'pack_200')
    obj = grant(ledger, provider, sku)
    if consumed:
        ledger.charge_pages('buyer', 124 if sku == 'starter' else 204)
    if sku == 'starter':
        pi_id = next(p['payment']['payment_intent'] for p in provider.objects.values() if p.get('object') == 'invoice_payment' and p['invoice'] == obj['invoice'])
    else: pi_id = obj['payment_intent']
    charge = provider.objects[provider.objects[pi_id]['latest_charge']]
    if reversal == 'refund':
        charge['amount_refunded'] = charge['amount']; charge['refunded'] = True
        ev = event(charge, 'charge.refunded')
    else:
        charge['disputed'] = True
        ev = event({'id': 'dp_synthetic', 'livemode': False, 'charge': charge['id'], 'payment_intent': pi_id, 'currency': 'usd', 'amount': charge['amount'], 'status': 'needs_response'}, 'charge.dispute.created')
    apply_webhook(ledger, ev, provider)
    before = ledger.get_or_create('buyer')
    assert before.credits >= 0 and before.plan_id == 'free'
    assert before.billing_hold is (consumed or reversal == 'dispute')
    if before.billing_hold: resolve_hold(ledger, obj['metadata']['purchase_ref'])
    apply_webhook(ledger, event(ev['data']['object'], ev['type']), provider)
    apply_webhook(ledger, event(obj), provider)
    after = ledger.get_or_create('buyer')
    assert not after.billing_hold and before.credits == after.credits and after.plan_id == 'free'
    assert after.pro  # Independent pack_200 purchase survives.


@pytest.mark.parametrize('sku', ['pack_50', 'starter'])
def test_early_reversal_before_any_paid_event_never_grants(ledger, provider, sku):
    obj = provider.paid(buy(ledger, provider, sku)['session_id'])
    pi_id = obj.get('payment_intent') or next(p['payment']['payment_intent'] for p in provider.objects.values() if p.get('object') == 'invoice_payment')
    ch = provider.objects[provider.objects[pi_id]['latest_charge']]
    ch['amount_refunded'] = ch['amount']; ch['refunded'] = True
    apply_webhook(ledger, event(ch, 'charge.refunded'), provider)
    apply_webhook(ledger, event(obj), provider)
    acct = ledger.get_or_create('buyer')
    assert acct.credits == 0 and acct.plan_id == 'free' and not acct.pro


def test_grant_and_event_marker_rollback_atomically(ledger, provider):
    ev = paid_event(buy(ledger, provider)['session_id'])
    with ledger.transaction() as db: db.execute("CREATE TRIGGER fail_grant BEFORE UPDATE ON accounts BEGIN SELECT RAISE(ABORT, 'synthetic outage'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError): apply_webhook(ledger, ev, provider)
    with ledger.transaction() as db:
        assert db.execute('SELECT count(*) FROM entitlements').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM webhook_events').fetchone()[0] == 0
        db.execute('DROP TRIGGER fail_grant')
    assert apply_webhook(ledger, ev, provider)['granted']


@pytest.mark.parametrize('kwargs', [dict(mode='wrong'), dict(mode='test', secret_key='sk_live_synthetic'), dict(mode='live', secret_key='sk_test_synthetic'), dict(webhook_secret='bad'), dict(checkout_origin='https://foreign.example'), dict(mode='live', checkout_origin='http://localhost:5173')])
def test_invalid_configuration_fails_closed(kwargs):
    with pytest.raises(BillingError): StripeBillingProvider(**kwargs)


def test_mode_bound_database_cannot_reuse_test_allowances_live(ledger):
    with pytest.raises(RuntimeError): PersistentLedger(ledger.database_path, mode='live')


def test_paid_webhook_recovers_ambiguous_checkout_without_browser_retry(ledger, provider):
    provider.fail_after_creation = True
    with pytest.raises(BillingError): buy(ledger, provider)
    sid = next(iter(provider.sessions.values()))['id']
    assert apply_webhook(PersistentLedger(ledger.database_path), paid_event(sid), provider)['granted']
    assert ledger.get_or_create('buyer').credits == 50
    assert buy(ledger, provider)['session_id'] == sid
    assert ledger.get_or_create('buyer').credits == 50


def test_concurrent_paid_deliveries_grant_exactly_once(ledger, provider):
    sid = buy(ledger, provider)['session_id']; ev = paid_event(sid)
    def deliver(i):
        e = copy.deepcopy(ev); e['id'] = 'evt_parallel_' + str(i)
        return apply_webhook(PersistentLedger(ledger.database_path), e, provider)
    with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(deliver, range(10)))
    assert sum(r['granted'] for r in results) == 1 and ledger.get_or_create('buyer').credits == 50


@pytest.mark.parametrize('sku', ['pack_50', 'starter'])
@pytest.mark.parametrize('kind', ['partial_refund', 'partial_dispute', 'dispute_won'])
def test_ambiguous_reversals_hold_without_negative_or_automatic_revival(ledger, provider, sku, kind):
    obj = grant(ledger, provider, sku)
    pi_id = obj.get('payment_intent') or next(p['payment']['payment_intent'] for p in provider.objects.values() if p.get('object') == 'invoice_payment')
    ch = provider.objects[provider.objects[pi_id]['latest_charge']]
    if kind == 'partial_refund':
        ch['amount_refunded'] = 1; ev = event(ch, 'charge.refunded')
    else:
        ev = event({'id': 'dp_synthetic', 'livemode': False, 'charge': ch['id'], 'payment_intent': pi_id, 'currency': 'usd', 'amount': 1 if kind == 'partial_dispute' else ch['amount'], 'status': 'won' if kind == 'dispute_won' else 'needs_response'}, 'charge.dispute.closed' if kind == 'dispute_won' else 'charge.dispute.created')
    apply_webhook(ledger, ev, provider)
    acct = ledger.get_or_create('buyer')
    assert acct.billing_hold and acct.credits == 0 and acct.plan_id == 'free'
    with pytest.raises(BillingError, match='reconciliation'): buy(ledger, provider, 'pack_200', key=str(uuid.uuid4()))
    from statement_to_excel.billing import InsufficientCredits
    with pytest.raises(InsufficientCredits): ledger.charge_pages('buyer', 1)
    apply_webhook(ledger, event(obj), provider)
    assert ledger.get_or_create('buyer').billing_hold


@pytest.mark.parametrize('status', ['unpaid', 'paused'])
def test_unpaid_active_object_cannot_restore_but_new_paid_cycle_recovers(ledger, provider, status):
    obj = grant(ledger, provider, 'starter'); sub = provider.objects[obj['subscription']]
    sub['status'] = status
    apply_webhook(ledger, event(sub, 'customer.subscription.updated'), provider)
    assert ledger.get_or_create('buyer').plan_id == 'free'
    sub['status'] = 'active'
    apply_webhook(ledger, event(sub, 'customer.subscription.updated'), provider)
    assert ledger.get_or_create('buyer').plan_id == 'free'
    start = sub['items']['data'][0]['current_period_start'] + 1000
    renewed = provider.paid(obj['id'], start)
    apply_webhook(ledger, event(provider.objects[renewed['invoice']], 'invoice.paid'), provider)
    assert ledger.get_or_create('buyer').plan_id == 'starter'


@pytest.mark.parametrize('field,value', [('livemode', True), ('currency', 'eur'), ('amount_requested', 1), ('amount_paid', 1)])
def test_conflicting_invoice_payment_evidence_grants_nothing(ledger, provider, field, value):
    obj = provider.paid(buy(ledger, provider, 'starter')['session_id'])
    payment = next(p for p in provider.objects.values() if p.get('object') == 'invoice_payment')
    payment[field] = value
    with pytest.raises(BillingError): apply_webhook(ledger, event(obj), provider)
    assert not ledger.get_or_create('buyer').pro


def test_unpaid_checkout_and_expired_returns_never_grant(ledger, provider):
    sid = buy(ledger, provider)['session_id']; obj = provider.objects[sid]
    assert not apply_webhook(ledger, event(obj), provider)['granted']
    assert ledger.get_or_create('buyer').credits == 0
    apply_webhook(ledger, event(obj, 'checkout.session.expired'), provider)
    assert api.checkout_status(ledger, sid, 'buyer')['status'] == 'expired'
    assert buy(ledger, provider, key='new-checkout-after-expiry')['session_id'] != sid


def test_slow_webhook_provider_does_not_block_health(ledger, provider, monkeypatch):
    sid = buy(ledger, provider)['session_id']; payload = json.dumps(paid_event(sid)).encode()
    entered, release = threading.Event(), threading.Event(); original = provider.call
    def slow(resource, method, *args, **kwargs):
        if resource == 'payment_intents':
            entered.set(); assert release.wait(3)
        return original(resource, method, *args, **kwargs)
    monkeypatch.setattr(provider, 'call', slow)
    monkeypatch.setattr(api, 'LEDGER', ledger); monkeypatch.setattr(api, 'PROVIDER', provider)
    with TestClient(api.app) as c, ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(c.post, '/api/stripe/webhook', content=payload, headers={'Stripe-Signature': sign(payload)})
        assert entered.wait(2)
        try:
            start = time.monotonic(); assert c.get('/api/health').status_code == 200
            assert time.monotonic() - start < .5
        finally: release.set()
        assert pending.result().status_code == 200


def test_terminal_before_payment_does_not_trap_pending_checkout_and_old_events_cannot_change_new_subscription(ledger, provider):
    sid = buy(ledger, provider, 'starter')['session_id']; old = provider.paid(sid)
    sub = provider.objects[old['subscription']]; sub['status'] = 'canceled'
    apply_webhook(ledger, event(sub, 'customer.subscription.deleted'), provider)
    fresh = grant(ledger, provider, 'business')
    apply_webhook(ledger, event(old), provider)
    ledger.charge_pages('buyer', 2)
    apply_webhook(ledger, event(sub, 'customer.subscription.deleted'), provider)
    acct = ledger.get_or_create('buyer')
    assert acct.plan_id == 'business' and acct.pages_used_this_cycle == 2


@pytest.mark.parametrize('mode', ['test', 'live'])
def test_real_stripe_sdk_serializes_pinned_api_and_server_owned_checkout_without_capability(ledger, mode):
    import stripe
    from urllib.parse import parse_qs
    calls = []
    class Transport(stripe.HTTPClient):
        name = 'synthetic-only'
        def request(self, method, url, headers=None, post_data=None, **kwargs):
            calls.append({'method': method, 'url': url, 'headers': headers, 'body': parse_qs(post_data or '')})
            fields = calls[-1]['body']; ref = fields['metadata[purchase_ref]'][0]
            return json.dumps({'id': 'cs_synthetic', 'object': 'checkout.session', 'livemode': mode == 'live', 'customer': 'cus_synthetic', 'metadata': {'app': APP, 'purchase_ref': ref}, 'mode': 'subscription', 'amount_total': 7900, 'currency': 'usd', 'url': 'https://checkout.stripe.com/synthetic-only'}), 200, {}
    client = stripe.StripeClient('sk_' + mode + '_synthetic_transport', stripe_version=API_VERSION, http_client=Transport(), max_network_retries=0)
    p = StripeBillingProvider('sk_' + mode + '_synthetic_transport', SECRET, mode=mode, client=client, portal_configuration='bpc_synthetic')
    p.create_checkout('cus_synthetic', 'business', 'stx_synthetic_idempotency', 'opaque_synthetic_purchase')
    assert len(calls) == 1
    sent = calls[0]
    assert sent['headers']['Stripe-Version'] == API_VERSION
    assert sent['headers']['Idempotency-Key'] == 'stx_synthetic_idempotency'
    assert sent['body']['line_items[0][price_data][unit_amount]'] == ['7900']
    assert sent['body']['line_items[0][quantity]'] == ['1']
    assert sent['body']['subscription_data[metadata][app]'] == [APP]
    assert 'account_id' not in json.dumps(sent['body'])


def test_subscription_reversal_outbox_retries_after_ambiguous_cancellation_and_restart(ledger, provider, monkeypatch):
    from statement_to_excel.payments import drain_actions
    obj = grant(ledger, provider, 'starter')
    payment = next(p for p in provider.objects.values() if p.get('object') == 'invoice_payment')
    ch = provider.objects[provider.objects[payment['payment']['payment_intent']]['latest_charge']]
    ch['amount_refunded'] = ch['amount']; ch['refunded'] = True
    original = provider.call
    def ambiguous(resource, method, *args, **kwargs):
        result = original(resource, method, *args, **kwargs)
        if resource == 'subscriptions' and method == 'cancel':
            raise BillingError('Synthetic response lost after cancellation')
        return result
    monkeypatch.setattr(provider, 'call', ambiguous)
    apply_webhook(ledger, event(ch, 'charge.refunded'), provider)
    acct = ledger.get_or_create('buyer')
    assert acct.billing_hold and acct.plan_id == 'free'
    assert provider.objects[obj['subscription']]['status'] == 'canceled'
    with pytest.raises(BillingError, match='confirmed'): resolve_hold(ledger, obj['metadata']['purchase_ref'])
    with pytest.raises(BillingError): buy(ledger, provider, 'business', key=str(uuid.uuid4()))
    with ledger.transaction() as db:
        pending = db.execute('SELECT * FROM stx_actions').fetchone()
        assert pending['complete'] == 0 and pending['last_error'] == 'confirmation_pending'
        db.execute('UPDATE stx_actions SET next_attempt=0')
    assert drain_actions(PersistentLedger(ledger.database_path), provider)['completed'] == 1
    assert not ledger.get_or_create('buyer').billing_hold
    cancels = [r for r in provider.requests if r[:2] == ('subscriptions', 'cancel')]
    assert len(cancels) == 1  # Resource-state retry, no second mutation.
    assert buy(ledger, provider, 'business', key=str(uuid.uuid4()))


def test_pending_cancellation_startup_retries_without_customer_request(ledger, provider, monkeypatch):
    from statement_to_excel.payments import _apply_webhook
    obj = grant(ledger, provider, 'starter')
    pi = next(p['payment']['payment_intent'] for p in provider.objects.values() if p.get('object') == 'invoice_payment')
    ch = provider.objects[provider.objects[pi]['latest_charge']]; ch['amount_refunded'] = ch['amount']
    _apply_webhook(ledger, event(ch, 'charge.refunded'), provider)
    monkeypatch.setattr(api, 'LEDGER', PersistentLedger(ledger.database_path)); monkeypatch.setattr(api, 'PROVIDER', provider)
    with TestClient(api.app):
        deadline = time.monotonic() + 3
        while ledger.get_or_create('buyer').billing_hold and time.monotonic() < deadline:
            time.sleep(.01)
        assert not ledger.get_or_create('buyer').billing_hold
    assert provider.objects[obj['subscription']]['status'] == 'canceled'


def test_outbox_never_cancels_foreign_customer_and_holds_until_confirmed(ledger, provider):
    from statement_to_excel.payments import _apply_webhook, drain_actions
    obj = grant(ledger, provider, 'starter')
    pi = next(p['payment']['payment_intent'] for p in provider.objects.values() if p.get('object') == 'invoice_payment')
    ch = provider.objects[provider.objects[pi]['latest_charge']]; ch['amount_refunded'] = ch['amount']
    _apply_webhook(ledger, event(ch, 'charge.refunded'), provider)
    provider.objects[obj['customer']]['metadata']['app'] = 'other-app'
    assert drain_actions(ledger, provider)['completed'] == 0
    assert not [r for r in provider.requests if r[:2] == ('subscriptions', 'cancel')]
    assert ledger.get_or_create('buyer').billing_hold


def test_paid_invoice_before_subscription_propagation_retries_without_losing_or_resetting_allowance(ledger, provider):
    obj = provider.paid(buy(ledger, provider, 'starter')['session_id'])
    sub = provider.objects[obj['subscription']]; sub['status'] = 'incomplete'
    invoice = event(provider.objects[obj['invoice']], 'invoice.paid')
    with pytest.raises(BillingError, match='confirmation'): apply_webhook(ledger, invoice, provider)
    assert not ledger.get_or_create('buyer').pro
    sub['status'] = 'active'
    apply_webhook(ledger, event(sub, 'customer.subscription.updated'), provider)
    assert not ledger.get_or_create('buyer').pro
    assert apply_webhook(ledger, invoice, provider)['granted']
    ledger.charge_pages('buyer', 2)
    apply_webhook(ledger, event(obj), provider)
    assert ledger.get_or_create('buyer').pages_used_this_cycle == 2


@pytest.mark.parametrize('mode', ['test', 'live'])
def test_both_modes_complete_subscription_portal_renewal_and_reversal(tmp_path, mode):
    p = PaymentDouble(mode); ledger = PersistentLedger(str(tmp_path / 'mode.sqlite3'), mode)
    grant(ledger, p, 'pack_200'); obj = grant(ledger, p, 'firm')
    assert create_portal(ledger, p, 'buyer')['portal_url'].startswith('https://billing.stripe.com/')
    ledger.charge_pages('buyer', 5)
    start = p.objects[obj['subscription']]['items']['data'][0]['current_period_start'] + 1000
    renewed = p.paid(obj['id'], start)
    apply_webhook(ledger, event(p.objects[renewed['invoice']], 'invoice.paid'), p)
    assert ledger.get_or_create('buyer').pages_used_this_cycle == 0
    pi_id = next(o['payment']['payment_intent'] for o in p.objects.values() if o.get('object') == 'invoice_payment' and o['invoice'] == renewed['invoice'])
    ch = p.objects[p.objects[pi_id]['latest_charge']]; ch['amount_refunded'] = ch['amount']
    apply_webhook(ledger, event(ch, 'charge.refunded'), p)
    acct = PersistentLedger(ledger.database_path, mode).get_or_create('buyer')
    assert acct.plan_id == 'free' and acct.credits == 200 and not acct.billing_hold
    assert p.objects[obj['subscription']]['status'] == 'canceled'
    apply_webhook(ledger, event(renewed), p)
    assert ledger.get_or_create('buyer').plan_id == 'free'


def test_hold_escalation_survives_two_cycle_reversals_during_pending_cancellation(ledger, provider, monkeypatch):
    from statement_to_excel.payments import _apply_webhook, drain_actions
    first = grant(ledger, provider, 'starter')
    start = provider.objects[first['subscription']]['items']['data'][0]['current_period_start'] + 1000
    newer = provider.paid(first['id'], start)
    apply_webhook(ledger, event(provider.objects[newer['invoice']], 'invoice.paid'), provider)
    ledger.charge_pages('buyer', 3)
    def refund(inv):
        pi = next(o['payment']['payment_intent'] for o in provider.objects.values() if o.get('object') == 'invoice_payment' and o['invoice'] == inv)
        ch = provider.objects[provider.objects[pi]['latest_charge']]; ch['amount_refunded'] = ch['amount']
        _apply_webhook(ledger, event(ch, 'charge.refunded'), provider)
    refund(first['invoice'])  # unused, only cancellation pending
    refund(newer['invoice'])  # consumed, must escalate the same purchase hold
    assert drain_actions(ledger, provider)['completed'] == 1
    with ledger.transaction() as db:
        hold = db.execute('SELECT * FROM stx_holds').fetchone()
        assert hold['reason'] == 'reversal_needs_reconciliation' and not hold['resolved']
    assert ledger.get_or_create('buyer').billing_hold


@pytest.mark.parametrize('mutation', ['mode', 'currency', 'intent'])
def test_early_reversal_rejects_conflicting_invoice_payment_association(ledger, provider, mutation):
    obj = provider.paid(buy(ledger, provider, 'starter')['session_id'])
    pay = next(o for o in provider.objects.values() if o.get('object') == 'invoice_payment')
    ch = provider.objects[provider.objects[pay['payment']['payment_intent']]['latest_charge']]
    ch['amount_refunded'] = ch['amount']
    original = provider.call
    def wrong(resource, method, *args, **kwargs):
        result = original(resource, method, *args, **kwargs)
        if resource == 'invoice_payments':
            if mutation == 'mode': result['data'][0]['livemode'] = True
            if mutation == 'currency': result['data'][0]['currency'] = 'eur'
            if mutation == 'intent': result['data'][0]['payment']['payment_intent'] = 'pi_conflict'
        return result
    provider.call = wrong
    with pytest.raises(BillingError): apply_webhook(ledger, event(ch, 'charge.refunded'), provider)
    assert not ledger.get_or_create('buyer').billing_hold
    with ledger.transaction() as db: assert not db.execute('SELECT 1 FROM stx_payments').fetchone()


def test_legacy_test_accounts_without_checkout_cannot_be_imported_live(tmp_path):
    import sqlite3
    path = str(tmp_path / 'legacy.sqlite3')
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE accounts(id TEXT PRIMARY KEY,plan_id TEXT,credits INTEGER,pages_used INTEGER,pro INTEGER)')
        db.execute("INSERT INTO accounts VALUES ('synthetic_legacy','free',200,3,1)")
    with pytest.raises(RuntimeError, match='separate'): PersistentLedger(path, 'live')
    with sqlite3.connect(path) as db: assert db.execute('SELECT credits FROM accounts').fetchone()[0] == 200


def test_billing_cannot_enable_without_hosted_management_configuration():
    with pytest.raises(BillingError, match='hosted management'):
        StripeBillingProvider('sk_test_synthetic_not_a_credential', SECRET, portal_configuration='')


def test_monthly_checkout_cannot_take_payment_with_invalid_portal_features(ledger, provider):
    provider.objects['bpc_synthetic'] = {'livemode': False, 'active': True, 'features': {'subscription_cancel': {'enabled': False}}}
    with pytest.raises(BillingError, match='Hosted management'): buy(ledger, provider, 'starter')
    assert not provider.sessions and not ledger.get_or_create('buyer').pro


def test_later_unused_cycle_refund_does_not_reopen_confirmed_cancellation_hold(ledger, provider):
    first = grant(ledger, provider, 'starter')
    start = provider.objects[first['subscription']]['items']['data'][0]['current_period_start'] + 1000
    newer = provider.paid(first['id'], start)
    apply_webhook(ledger, event(provider.objects[newer['invoice']], 'invoice.paid'), provider)
    for invoice in [first['invoice'], newer['invoice']]:
        pi = next(o['payment']['payment_intent'] for o in provider.objects.values() if o.get('object') == 'invoice_payment' and o['invoice'] == invoice)
        ch = provider.objects[provider.objects[pi]['latest_charge']]; ch['amount_refunded'] = ch['amount']
        apply_webhook(ledger, event(ch, 'charge.refunded'), provider)
        assert not ledger.get_or_create('buyer').billing_hold


@pytest.mark.parametrize(('fmt','preview'), [('xlsx',False),('csv',False),('json',False),('xlsx',True),('csv',True)])
def test_payment_hold_returns_reconciliation_error_without_debit(ledger, provider, monkeypatch, fixtures_dir, fmt, preview):
    obj = grant(ledger, provider)
    ledger.charge_pages('buyer', 4)
    ch = provider.objects[provider.objects[obj['payment_intent']]['latest_charge']]; ch['amount_refunded'] = ch['amount']
    apply_webhook(ledger, event(ch, 'charge.refunded'), provider)
    monkeypatch.setattr(api, 'LEDGER', ledger); monkeypatch.setattr(api, 'PROVIDER', provider)
    with TestClient(api.app) as c:
        response = c.post('/api/convert', files={'file': ('synthetic.pdf', (fixtures_dir/'acmebank.pdf').read_bytes(), 'application/pdf')}, data={'account_id': 'buyer', 'fmt': fmt, 'preview': str(preview).lower()}, headers={'Idempotency-Key': 'synthetic-held-conversion-key'})
        assert response.status_code == 409 and response.json()['error'] == 'billing_hold'
    assert ledger.get_or_create('buyer').credits == 0
    with ledger.transaction() as db: assert not db.execute('SELECT 1 FROM conversion_charges').fetchone()
