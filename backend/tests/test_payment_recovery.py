"""Cycle-specific service and provider-confirmed choice recovery; synthetic only."""
import copy
import time
import uuid

import pytest
from statement_to_excel.billing import BillingError, PersistentLedger, apply_webhook
from statement_to_excel.payments import drain_actions
from tests.test_billing_stripe import PaymentDouble, buy, grant, event


@pytest.fixture
def ledger(tmp_path): return PersistentLedger(str(tmp_path / 'billing.sqlite3'))


@pytest.fixture
def provider(): return PaymentDouble()


def invoice_charge(provider, invoice):
    pi = next(o['payment']['payment_intent'] for o in provider.objects.values() if o.get('object') == 'invoice_payment' and o['invoice'] == invoice)
    return provider.objects[provider.objects[pi]['latest_charge']]


@pytest.mark.parametrize('used', [0, 3])
@pytest.mark.parametrize('lost_cancel', [False, True])
def test_old_only_refund_retains_newer_service_after_cancel_restart_and_delays(ledger, provider, monkeypatch, used, lost_cancel):
    grant(ledger, provider, 'pack_200')
    old = copy.deepcopy(grant(ledger, provider, 'starter'))
    start = provider.objects[old['subscription']]['items']['data'][0]['current_period_start'] + 1000
    newer = provider.paid(old['id'], start)
    invoice = copy.deepcopy(provider.objects[newer['invoice']])
    apply_webhook(ledger, event(invoice, 'invoice.paid'), provider)
    if used: ledger.charge_pages('buyer', used)
    ch = invoice_charge(provider, old['invoice']); ch['amount_refunded'] = ch['amount']
    original = provider.call
    def lost(resource, method, *args, **kwargs):
        result = original(resource, method, *args, **kwargs)
        if lost_cancel and (resource, method) == ('subscriptions', 'cancel'):
            raise BillingError('Synthetic cancellation response loss')
        return result
    monkeypatch.setattr(provider, 'call', lost)
    reversal = event(ch, 'charge.refunded')
    apply_webhook(ledger, reversal, provider)
    restarted = PersistentLedger(ledger.database_path)
    acct = restarted.get_or_create('buyer')
    assert acct.plan_id == 'starter' and acct.pages_used_this_cycle == used and acct.credits == 200
    assert not acct.billing_hold  # Known paid B is not an ambiguous reversal of A.
    with restarted.transaction() as db:
        state = db.execute('SELECT * FROM stx_subscriptions').fetchone()
        assert state['terminal'] and state['retained_invoice_id'] == newer['invoice']
        db.execute('UPDATE stx_actions SET next_attempt=0')
    drain_actions(restarted, provider)
    assert len([r for r in provider.requests if r[:2] == ('subscriptions', 'cancel')]) == 1
    for ev in [reversal, event(ch, 'charge.refunded'), event(old), event(invoice, 'invoice.paid'), event(provider.objects[old['subscription']], 'customer.subscription.deleted')]:
        apply_webhook(restarted, ev, provider)
        assert restarted.get_or_create('buyer').pages_used_this_cycle == used
        assert restarted.get_or_create('buyer').plan_id == 'starter'
    restarted.charge_pages('buyer', 2)
    assert restarted.get_or_create('buyer').pages_used_this_cycle == used + 2
    with restarted.transaction() as db:
        assert db.execute('SELECT used_pages FROM stx_cycles WHERE invoice_id=?', (newer['invoice'],)).fetchone()[0] == used + 2
        assert not db.execute('SELECT 1 FROM stx_holds WHERE resolved=0').fetchone()
    with pytest.raises(BillingError, match='existing subscription'): buy(restarted, provider, 'business', str(uuid.uuid4()))
    late = provider.paid(old['id'], start + 1000)
    apply_webhook(restarted, event(provider.objects[late['invoice']], 'invoice.paid'), provider)
    assert restarted.get_or_create('buyer').pages_used_this_cycle == used + 2
    current_charge = invoice_charge(provider, newer['invoice']); current_charge['amount_refunded'] = current_charge['amount']
    apply_webhook(restarted, event(current_charge, 'charge.refunded'), provider)
    acct = restarted.get_or_create('buyer')
    assert acct.plan_id == 'free' and acct.credits == 200 and acct.billing_hold


def test_retained_paid_cycle_expires_without_webhook(ledger, provider, monkeypatch):
    old = copy.deepcopy(grant(ledger, provider, 'starter'))
    start = provider.objects[old['subscription']]['items']['data'][0]['current_period_start'] + 1000
    newer = provider.paid(old['id'], start)
    apply_webhook(ledger, event(provider.objects[newer['invoice']], 'invoice.paid'), provider)
    ch = invoice_charge(provider, old['invoice']); ch['amount_refunded'] = ch['amount']
    apply_webhook(ledger, event(ch, 'charge.refunded'), provider)
    assert ledger.get_or_create('buyer').plan_id == 'starter'
    monkeypatch.setattr('statement_to_excel.payments.time.time', lambda: start + 30 * 86400 + 1)
    assert PersistentLedger(ledger.database_path).get_or_create('buyer').plan_id == 'free'


@pytest.mark.parametrize(('before','after'), [('pack_50','pack_200'), ('pack_50','starter'), ('starter','business'), ('starter','pack_50')])
def test_changed_choice_expires_same_owned_session_and_preserves_history(ledger, provider, before, after):
    old = buy(ledger, provider, before)
    assert buy(ledger, provider, before, str(uuid.uuid4())) == old
    newer = buy(ledger, provider, after, str(uuid.uuid4()))
    assert newer['session_id'] != old['session_id']
    expires = [r for r in provider.requests if r[:2] == ('checkout.sessions', 'expire')]
    assert len(expires) == 1 and expires[0][2][0] == old['session_id']
    with ledger.transaction() as db:
        assert db.execute('SELECT state FROM checkout_requests WHERE session_id=?', (old['session_id'],)).fetchone()[0] == 'expired'
        assert db.execute('SELECT COUNT(*) FROM checkout_aliases').fetchone()[0] == 1
    assert buy(ledger, provider, before) == old
    assert ledger.get_or_create('buyer').credits == 0


def test_choice_expiry_response_loss_retrieves_same_session_after_restart(ledger, provider, monkeypatch):
    old = buy(ledger, provider, 'starter'); original = provider.call
    def lost(resource, method, *args, **kwargs):
        result = original(resource, method, *args, **kwargs)
        if (resource, method) == ('checkout.sessions','expire'): raise BillingError('Synthetic expiry response loss')
        return result
    monkeypatch.setattr(provider, 'call', lost)
    key = str(uuid.uuid4())
    with pytest.raises(BillingError): buy(ledger, provider, 'business', key)
    assert provider.objects[old['session_id']]['status'] == 'expired'
    newer = buy(PersistentLedger(ledger.database_path), provider, 'business', key)
    assert newer['session_id'] != old['session_id']
    assert len([r for r in provider.requests if r[:2] == ('checkout.sessions','expire')]) == 1


@pytest.mark.parametrize('mutation', ['customer', 'metadata', 'livemode', 'amount_total', 'mode', 'processing', 'paid'])
def test_choice_cannot_expire_conflicting_or_inflight_payment(ledger, provider, mutation):
    old = buy(ledger, provider); obj = provider.objects[old['session_id']]
    if mutation == 'customer': obj['customer'] = 'cus_foreign'
    elif mutation == 'metadata': obj['metadata'] = {'app': 'foreign'}
    elif mutation == 'livemode': obj['livemode'] = True
    elif mutation == 'amount_total': obj['amount_total'] = 1
    elif mutation == 'mode': obj['mode'] = 'subscription'
    elif mutation == 'processing': obj['payment_intent'] = 'pi_processing'
    else: provider.paid(obj['id'])
    with pytest.raises(BillingError): buy(ledger, provider, 'business', str(uuid.uuid4()))
    assert not [r for r in provider.requests if r[:2] == ('checkout.sessions','expire')]
    assert len(provider.sessions) == 1


def test_payment_wins_expiry_race_without_duplicate_or_return_grant(ledger, provider, monkeypatch):
    old = buy(ledger, provider); original = provider.call
    def race(resource, method, *args, **kwargs):
        if (resource, method) == ('checkout.sessions','expire'): provider.paid(old['session_id'])
        return original(resource, method, *args, **kwargs)
    monkeypatch.setattr(provider, 'call', race)
    key = str(uuid.uuid4())
    with pytest.raises(BillingError): buy(ledger, provider, 'starter', key)
    with pytest.raises(BillingError): buy(PersistentLedger(ledger.database_path), provider, 'starter', key)
    assert len(provider.sessions) == 1 and ledger.get_or_create('buyer').credits == 0
    apply_webhook(ledger, event(provider.objects[old['session_id']]), provider)
    assert ledger.get_or_create('buyer').credits == 50
    assert buy(ledger, provider, 'starter', key)


def test_unknown_session_keeps_original_ambiguous_create_key(ledger, provider):
    provider.fail_after_creation = True
    with pytest.raises(BillingError): buy(ledger, provider, 'starter')
    with pytest.raises(BillingError, match='original choice'): buy(ledger, provider, 'business', str(uuid.uuid4()))
    assert len(provider.sessions) == 1
    resumed = buy(PersistentLedger(ledger.database_path), provider, 'starter')
    assert resumed['session_id'] == next(iter(provider.sessions.values()))['id']


def test_paid_renewal_before_old_refund_is_recovered_when_its_webhook_is_delayed(ledger, provider):
    old = copy.deepcopy(grant(ledger, provider, 'starter'))
    start = int(time.time()) - 10
    newer = provider.paid(old['id'], start)  # Stripe paid; no B webhook yet.
    ch = invoice_charge(provider, old['invoice']); ch['amount_refunded'] = ch['amount']
    apply_webhook(ledger, event(ch, 'charge.refunded'), provider)
    restarted = PersistentLedger(ledger.database_path)
    assert restarted.get_or_create('buyer').plan_id == 'free'  # refund is not a paid webhook
    apply_webhook(restarted, event(provider.objects[newer['invoice']], 'invoice.paid'), provider)
    assert restarted.get_or_create('buyer').plan_id == 'starter'
    restarted.charge_pages('buyer', 3)
    apply_webhook(restarted, event(provider.objects[newer['invoice']], 'invoice.paid'), provider)
    assert restarted.get_or_create('buyer').pages_used_this_cycle == 3
    assert not restarted.get_or_create('buyer').billing_hold


def test_old_refund_cannot_revive_service_ended_by_unrelated_terminal_event(ledger, provider):
    old = copy.deepcopy(grant(ledger, provider, 'starter'))
    start = provider.objects[old['subscription']]['items']['data'][0]['current_period_start'] + 1000
    newer = provider.paid(old['id'], start)
    apply_webhook(ledger, event(provider.objects[newer['invoice']], 'invoice.paid'), provider)
    sub = provider.objects[old['subscription']]; sub['status'] = 'canceled'
    apply_webhook(ledger, event(sub, 'customer.subscription.deleted'), provider)
    ch = invoice_charge(provider, old['invoice']); ch['amount_refunded'] = ch['amount']
    apply_webhook(ledger, event(ch, 'charge.refunded'), provider)
    assert ledger.get_or_create('buyer').plan_id == 'free'
    with ledger.transaction() as db:
        assert db.execute('SELECT retained_invoice_id FROM stx_subscriptions').fetchone()[0] is None


@pytest.mark.parametrize('ordering', ['before', 'same_second', 'after', 'missing', 'missing_cutoff'])
def test_late_paid_cycle_requires_proven_pre_stop_ordering_and_retains_a_durable_hold_otherwise(ledger, provider, ordering):
    from statement_to_excel.payments import resolve_hold
    old = copy.deepcopy(grant(ledger, provider, 'starter'))
    newer = provider.paid(old['id'], int(time.time()) - 10)
    invoice = provider.objects[newer['invoice']]
    cutoff = int(time.time())
    if ordering == 'missing': invoice['status_transitions'] = {}
    else: invoice['status_transitions']['paid_at'] = cutoff + {'before': -2, 'same_second': 0, 'after': 1, 'missing_cutoff': -2}[ordering]
    # Provider propagation omitted latest_invoice at the stop. Its later paid
    # webhook must use full immutable payment/period evidence, not delivery order.
    provider.objects[old['subscription']]['latest_invoice'] = None
    ch = invoice_charge(provider, old['invoice']); ch['amount_refunded'] = ch['amount']
    reversal = event(ch, 'charge.refunded'); reversal['created'] = cutoff
    if ordering == 'missing_cutoff': reversal.pop('created')
    apply_webhook(ledger, reversal, provider)
    restarted = PersistentLedger(ledger.database_path)
    apply_webhook(restarted, event(invoice, 'invoice.paid'), provider)
    acct = restarted.get_or_create('buyer')
    if ordering == 'before':
        assert acct.plan_id == 'starter' and not acct.billing_hold
        restarted.charge_pages('buyer', 3)
        apply_webhook(restarted, event(invoice, 'invoice.paid'), provider)
        assert restarted.get_or_create('buyer').pages_used_this_cycle == 3
    else:
        assert acct.plan_id == 'free' and acct.billing_hold
        with restarted.transaction() as db:
            hold = db.execute('SELECT * FROM stx_holds').fetchone()
            assert hold['reason'] == 'paid_cycle_after_renewal_stop' and not hold['resolved']
        resolve_hold(restarted, old['metadata']['purchase_ref'])
        apply_webhook(restarted, event(invoice, 'invoice.paid'), provider)
        assert not restarted.get_or_create('buyer').billing_hold  # duplicate won't reopen it
        assert restarted.get_or_create('buyer').plan_id == 'free'


def test_consumed_old_reversal_hold_survives_cancel_and_preserves_newer_usage_until_resolution(ledger, provider):
    from statement_to_excel.payments import resolve_hold
    old = copy.deepcopy(grant(ledger, provider, 'starter')); ledger.charge_pages('buyer', 2)
    start = provider.objects[old['subscription']]['items']['data'][0]['current_period_start'] + 1000
    newer = provider.paid(old['id'], start)
    apply_webhook(ledger, event(provider.objects[newer['invoice']], 'invoice.paid'), provider)
    ledger.charge_pages('buyer', 3)
    ch = invoice_charge(provider, old['invoice']); ch['amount_refunded'] = ch['amount']
    apply_webhook(ledger, event(ch, 'charge.refunded'), provider)
    acct = PersistentLedger(ledger.database_path).get_or_create('buyer')
    assert acct.plan_id == 'starter' and acct.pages_used_this_cycle == 3 and acct.billing_hold
    with ledger.transaction() as db:
        assert db.execute('SELECT used_pages FROM stx_cycles WHERE invoice_id=?', (old['invoice'],)).fetchone()[0] == 2
        assert db.execute('SELECT reason FROM stx_holds WHERE resolved=0').fetchone()[0] == 'reversal_needs_reconciliation'
    resolve_hold(ledger, old['metadata']['purchase_ref'])
    ledger.charge_pages('buyer', 1)
    assert ledger.get_or_create('buyer').pages_used_this_cycle == 4


def test_changed_sku_with_reused_request_key_never_expires_original(ledger, provider):
    original = buy(ledger, provider, 'starter')
    with pytest.raises(BillingError, match='another request'): buy(ledger, provider, 'business')
    assert provider.objects[original['session_id']]['status'] == 'open'
    assert not [r for r in provider.requests if r[:2] == ('checkout.sessions', 'expire')]


def test_old_only_dispute_preserves_known_paid_newer_cycle_and_unresolved_owner_hold(ledger, provider):
    from statement_to_excel.payments import resolve_hold
    grant(ledger, provider, 'pack_200')
    old = copy.deepcopy(grant(ledger, provider, 'starter'))
    start = provider.objects[old['subscription']]['items']['data'][0]['current_period_start'] + 1000
    newer = provider.paid(old['id'], start)
    apply_webhook(ledger, event(provider.objects[newer['invoice']], 'invoice.paid'), provider)
    ledger.charge_pages('buyer', 3)
    ch = invoice_charge(provider, old['invoice'])
    disputed = {'id': 'dp_synthetic_old_cycle', 'livemode': False, 'charge': ch['id'], 'payment_intent': ch['payment_intent'], 'currency': 'usd', 'amount': ch['amount'], 'status': 'needs_response'}
    apply_webhook(ledger, event(disputed, 'charge.dispute.created'), provider)
    restarted = PersistentLedger(ledger.database_path)
    acct = restarted.get_or_create('buyer')
    assert acct.plan_id == 'starter' and acct.pages_used_this_cycle == 3 and acct.credits == 200 and acct.billing_hold
    apply_webhook(restarted, event(disputed, 'charge.dispute.updated'), provider)
    with restarted.transaction() as db:
        assert db.execute('SELECT complete FROM stx_actions').fetchone()[0] == 1
        assert db.execute('SELECT resolved FROM stx_holds').fetchone()[0] == 0
    resolve_hold(restarted, old['metadata']['purchase_ref'])
    restarted.charge_pages('buyer', 1)
    assert restarted.get_or_create('buyer').pages_used_this_cycle == 4


def test_dispute_update_delivered_first_uses_dispute_inception_not_update_time(ledger, provider):
    old = copy.deepcopy(grant(ledger, provider, 'starter'))
    now = int(time.time())
    newer = provider.paid(old['id'], now - 15)
    invoice = provider.objects[newer['invoice']]
    invoice['status_transitions']['paid_at'] = now - 10
    ch = invoice_charge(provider, old['invoice'])
    disputed = {'id': 'dp_synthetic_updated_first', 'created': now - 20, 'livemode': False, 'charge': ch['id'], 'payment_intent': ch['payment_intent'], 'currency': 'usd', 'amount': ch['amount'], 'status': 'under_review'}
    updated = event(disputed, 'charge.dispute.updated'); updated['created'] = now
    apply_webhook(ledger, updated, provider)
    with ledger.transaction() as db:
        assert db.execute('SELECT renewal_stop_at FROM stx_subscriptions').fetchone()[0] == now - 20
    apply_webhook(PersistentLedger(ledger.database_path), event(invoice, 'invoice.paid'), provider)
    acct = ledger.get_or_create('buyer')
    assert acct.plan_id == 'free' and acct.billing_hold
