"""Signed synthetic Dahlia snapshots and unchanged Clover HTTP requests.

No provider API calls or captured provider payloads. Signatures use the real
clock. Object tags exercise the installed SDK's actual recursive conversion.
"""
import copy
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from statement_to_excel import api
from statement_to_excel.billing import BillingError, PersistentLedger, apply_webhook
from statement_to_excel.payments import API_VERSION, EVENTS, WEBHOOK_API_VERSION
from tests.test_billing_stripe import PaymentDouble, buy, event, sign


@pytest.fixture(params=['test', 'live'])
def billing(tmp_path, request):
    mode = request.param
    return PersistentLedger(str(tmp_path / 'billing.sqlite3'), mode), PaymentDouble(mode)


def snapshot(obj, kind='checkout.session.completed'):
    result = event(obj, kind)
    result['object'] = 'event'
    obj = result['data']['object']
    obj['object'] = ('checkout.session' if kind.startswith('checkout.') else
                     'invoice' if kind.startswith('invoice.') else
                     'subscription' if kind.startswith('customer.subscription.') else
                     'dispute' if kind.startswith('charge.dispute.') else 'charge')
    for key, item_type in [('lines', 'line_item'), ('items', 'subscription_item')]:
        if key in obj:
            obj[key]['object'] = 'list'
            for item in obj[key]['data']:
                item['object'] = item_type
    # New/unknown nested fields must survive SDK conversion, not be silently
    # projected onto the SDK's older generated type annotations.
    obj['synthetic_extension'] = {'nullable': None, 'items': [{'enabled': True, 'value': 1}]}
    return result


def deliver(ledger, provider, obj, kind='checkout.session.completed', envelope=None):
    envelope = envelope or snapshot(obj, kind)
    payload = json.dumps(envelope).encode()
    verified = provider.verify_event(payload, sign(payload))
    assert verified == envelope
    return apply_webhook(ledger, verified, provider)


def state(ledger):
    with ledger.transaction() as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name: [tuple(r) for r in db.execute(f'SELECT * FROM "{name}" ORDER BY rowid')] for name in tables}


@pytest.mark.parametrize('version', [API_VERSION, '2026-04-22.dahlia', '2026-09-30.endive',
    '2026-08-26', '2026-08-26.dahlia-extra', '', None, 'missing'])
def test_only_exact_target_delivery_is_accepted_before_mutation(billing, monkeypatch, version):
    ledger, provider = billing
    sid = buy(ledger, provider)['session_id']
    obj = provider.paid(sid)
    envelope = snapshot(obj)
    if version == 'missing': envelope.pop('api_version')
    else: envelope['api_version'] = version
    before = state(ledger); calls = len(provider.requests)
    monkeypatch.setattr(api, 'LEDGER', ledger); monkeypatch.setattr(api, 'PROVIDER', provider)
    payload = json.dumps(envelope).encode()
    with TestClient(api.app) as client:
        response = client.post('/api/stripe/webhook', content=payload, headers={'Stripe-Signature': sign(payload)})
    assert response.status_code == 400 and response.json()['detail'] == 'Unsupported webhook API version.'
    with pytest.raises(BillingError, match='Unsupported webhook API version'):
        apply_webhook(ledger, envelope, provider)
    assert state(ledger) == before and len(provider.requests) == calls


@pytest.mark.parametrize('invalid', ['missing', 'malformed', 'wrong_secret', 'expired', 'tampered'])
def test_signature_guards_still_precede_target_version_financial_work(billing, monkeypatch, invalid):
    ledger, provider = billing
    obj = provider.paid(buy(ledger, provider)['session_id'])
    payload = json.dumps(snapshot(obj)).encode()
    signature = sign(payload)
    if invalid == 'missing': signature = ''
    elif invalid == 'malformed': signature = 'not-a-signature'
    elif invalid == 'wrong_secret': signature = sign(payload, secret='synthetic-wrong-secret')
    elif invalid == 'expired': signature = sign(payload, timestamp=int(time.time()) - 600)
    else: payload += b' '
    before = state(ledger); calls = len(provider.requests)
    monkeypatch.setattr(api, 'LEDGER', ledger); monkeypatch.setattr(api, 'PROVIDER', provider)
    with TestClient(api.app) as client:
        response = client.post('/api/stripe/webhook', content=payload, headers={'Stripe-Signature': signature})
    assert response.status_code == 400 and state(ledger) == before and len(provider.requests) == calls


@pytest.mark.parametrize('level', ['event', 'object'])
def test_signed_target_mode_mismatch_cannot_mutate_owned_purchase(billing, monkeypatch, level):
    ledger, provider = billing
    envelope = snapshot(provider.paid(buy(ledger, provider)['session_id']))
    target = envelope if level == 'event' else envelope['data']['object']
    target['livemode'] = not target['livemode']
    before = state(ledger); calls = len(provider.requests)
    monkeypatch.setattr(api, 'LEDGER', ledger); monkeypatch.setattr(api, 'PROVIDER', provider)
    payload = json.dumps(envelope).encode()
    with TestClient(api.app) as client:
        response = client.post('/api/stripe/webhook', content=payload, headers={'Stripe-Signature': sign(payload)})
    assert response.status_code == 400 and state(ledger) == before and len(provider.requests) == calls


@pytest.mark.parametrize('kind', sorted(EVENTS))
def test_all_twelve_signed_snapshot_types_keep_owned_dictionary_fields_and_replay_guards(billing, kind):
    ledger, provider = billing
    assert WEBHOOK_API_VERSION == '2026-08-26.dahlia' != API_VERSION == '2026-02-25.clover'
    sku = 'starter' if kind.startswith(('invoice.', 'customer.subscription.')) else 'pack_50'
    sid = buy(ledger, provider, sku)['session_id']
    obj = provider.paid(sid)
    expected_plan, expected_credits = 'free', 0
    if kind.startswith('checkout.'):
        if kind.endswith(('expired', 'async_payment_failed')):
            obj['payment_status'] = 'unpaid'
            obj['status'] = 'expired' if kind.endswith('expired') else 'complete'
        else: expected_credits = 50
    else:
        deliver(ledger, provider, obj)
        expected_plan, expected_credits = ('starter', 0) if sku == 'starter' else ('free', 50)
        if kind.startswith('invoice.'):
            obj = copy.deepcopy(provider.objects[obj['invoice']])
            if kind.endswith('payment_failed'):
                provider.objects[provider.objects[sid]['subscription']]['status'] = 'past_due'
                obj.update(status='open', amount_paid=0)
        elif kind.startswith('customer.subscription.'):
            obj = provider.objects[obj['subscription']]
            obj['cancel_at_period_end'] = True
            if kind.endswith('deleted'):
                obj.update(status='canceled', ended_at=int(time.time()))
                expected_plan = 'free'
        else:
            charge = provider.objects[provider.objects[obj['payment_intent']]['latest_charge']]
            expected_credits = 0
            if kind == 'charge.refunded':
                charge.update(amount_refunded=charge['amount'], refunded=True)
                obj = charge
            else:
                charge['disputed'] = True
                obj = {'id': 'dp_synthetic', 'created': int(time.time()) - 1, 'livemode': provider.mode == 'live',
                    'charge': charge['id'], 'payment_intent': charge['payment_intent'], 'amount': charge['amount'],
                    'currency': 'usd', 'status': 'lost' if kind.endswith('closed') else 'needs_response'}
    envelope = snapshot(obj, kind)
    deliver(ledger, provider, obj, envelope=envelope)
    account = ledger.get_or_create('buyer')
    assert (account.plan_id, account.credits) == (expected_plan, expected_credits)
    before = state(ledger)
    assert deliver(ledger, provider, obj, envelope=envelope)['duplicate']
    assert state(ledger) == before


def test_signed_target_renewal_old_refund_and_out_of_order_delivery_retain_paid_service(billing):
    ledger, provider = billing
    pack = provider.paid(buy(ledger, provider, 'pack_200')['session_id']); deliver(ledger, provider, pack)
    old = copy.deepcopy(provider.paid(buy(ledger, provider, 'starter', str(uuid.uuid4()))['session_id']))
    old_invoice = copy.deepcopy(provider.objects[old['invoice']])
    deliver(ledger, provider, old_invoice, 'invoice.paid')  # Invoice before Checkout.
    deliver(ledger, provider, old)
    newer = provider.paid(old['id'], provider.objects[old['subscription']]['items']['data'][0]['current_period_start'] + 100)
    newer_invoice = copy.deepcopy(provider.objects[newer['invoice']])
    deliver(ledger, provider, newer_invoice, 'invoice.paid')
    ledger.charge_pages('buyer', 3)
    payment = next(p for p in provider.objects.values() if p.get('object') == 'invoice_payment' and p['invoice'] == old['invoice'])
    charge = provider.objects[provider.objects[payment['payment']['payment_intent']]['latest_charge']]
    charge.update(amount_refunded=charge['amount'], refunded=True)
    reversal = snapshot(charge, 'charge.refunded')
    deliver(ledger, provider, charge, envelope=reversal)
    restarted = PersistentLedger(ledger.database_path, provider.mode)
    for obj, kind in [(newer_invoice, 'invoice.paid'), (old_invoice, 'invoice.paid'), (old, 'checkout.session.completed'),
                      (provider.objects[old['subscription']], 'customer.subscription.deleted')]:
        deliver(restarted, provider, obj, kind)
    assert deliver(restarted, provider, charge, envelope=reversal)['duplicate']
    account = restarted.get_or_create('buyer')
    assert account.plan_id == 'starter' and account.included_remaining() == 117 and account.credits == 200
    assert not account.billing_hold


def test_valid_signed_target_foreign_event_is_inert(billing):
    ledger, provider = billing
    buy(ledger, provider)  # An unrelated owned pending request must be untouched.
    before = state(ledger)
    obj = {'id': 'cs_foreign', 'livemode': provider.mode == 'live', 'customer': 'cus_foreign',
        'metadata': {'app': 'other-app', 'account_id': 'buyer'}, 'payment_status': 'paid'}
    assert deliver(ledger, provider, obj)['ignored']
    assert state(ledger) == before
