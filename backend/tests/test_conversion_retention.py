"""Bounded retry metadata retention; payment idempotency remains durable."""

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import statement_to_excel.api as api
import statement_to_excel.billing as billing
from statement_to_excel.billing import (
    CONVERSION_IDEMPOTENCY_TTL_SECONDS as TTL,
    InsufficientCredits, Ledger, PersistentLedger,
)


@pytest.fixture
def clock(monkeypatch):
    now = [2_000_000_000.0]
    # Change this module's clock, not the event loop, Stripe SDK or test runner.
    monkeypatch.setattr(billing, "time", SimpleNamespace(time=lambda: now[0]))
    return now


@pytest.fixture(params=["memory", "sqlite"])
def ledger(request, tmp_path):
    if request.param == "memory":
        return Ledger()
    return PersistentLedger(str(tmp_path / "billing.sqlite3"))


def restart(ledger):
    return PersistentLedger(ledger.database_path) if isinstance(ledger, PersistentLedger) else ledger


def records(ledger):
    if isinstance(ledger, PersistentLedger):
        with closing(ledger.connect()) as db:
            return {row['request_key']: dict(row) for row in db.execute("SELECT * FROM conversion_charges")}
    return {key: {'created_at': row[3], 'fingerprint': row[1]} for key, row in ledger._conversion_charges.items()}


def test_exact_24_hour_replay_keeps_original_timestamp_and_debit(ledger, clock):
    created_at = clock[0]
    first = ledger.charge_pages_once("buyer", 1, "retry-key", "payload-A")
    clock[0] += TTL - 1
    ledger = restart(ledger)
    assert ledger.charge_pages_once("buyer", 1, "retry-key", "payload-A") == first
    clock[0] += 1
    assert ledger.purge_conversion_charges() == 0
    assert ledger.conversion_charge("buyer", "retry-key", "payload-A") == first
    assert ledger.charge_pages_once("buyer", 1, "retry-key", "payload-A") == first
    assert records(ledger)['retry-key']['created_at'] == created_at
    assert ledger.get_or_create("buyer").pages_used_this_cycle == 1
    with pytest.raises(ValueError, match="another conversion"):
        ledger.charge_pages_once("buyer", 1, "retry-key", "payload-B")


@pytest.mark.parametrize("payload", ["payload-A", "payload-B"])
def test_after_24_hours_key_is_new_request_even_for_different_payload(ledger, clock, payload):
    ledger.charge_pages_once("buyer", 1, "retry-key", "payload-A")
    clock[0] += TTL + 0.001
    ledger = restart(ledger)
    assert ledger.conversion_charge("buyer", "retry-key", payload) is None
    second = ledger.charge_pages_once("buyer", 1, "retry-key", payload)
    assert second['pages'] == 1
    assert ledger.get_or_create("buyer").pages_used_this_cycle == 2
    assert records(ledger)['retry-key']['created_at'] == clock[0]
    assert records(ledger)['retry-key']['fingerprint'] == payload


def test_concurrent_replays_after_expiry_make_one_new_debit(ledger, clock):
    ledger.charge_pages_once("buyer", 1, "retry-key", "payload-A")
    clock[0] += TTL + 0.001
    def debit(_):
        return restart(ledger).charge_pages_once("buyer", 1, "retry-key", "payload-A")
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(debit, range(16)))
    assert all(response == responses[0] for response in responses)
    assert ledger.get_or_create("buyer").pages_used_this_cycle == 2
    assert len(records(ledger)) == 1
    assert records(ledger)['retry-key']['created_at'] == clock[0]


def test_expired_key_race_with_different_payloads_has_one_winner(ledger, clock):
    ledger.charge_pages_once("buyer", 1, "retry-key", "payload-A")
    clock[0] += TTL + 0.001
    def debit(payload):
        try:
            return restart(ledger).charge_pages_once("buyer", 1, "retry-key", payload)
        except ValueError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(debit, ["payload-B", "payload-C"]))
    assert responses.count("conflict") == 1
    assert sum(isinstance(response, dict) for response in responses) == 1
    assert ledger.get_or_create("buyer").pages_used_this_cycle == 2
    assert len(records(ledger)) == 1


def test_expired_retry_cannot_bypass_exhausted_allowance(ledger, clock):
    first = ledger.charge_pages_once("buyer", 3, "retry-key", "payload-A")
    clock[0] += TTL
    assert ledger.charge_pages_once("buyer", 3, "retry-key", "payload-A") == first
    clock[0] += 0.001
    with pytest.raises(InsufficientCredits):
        restart(ledger).charge_pages_once("buyer", 3, "retry-key", "payload-A")
    assert records(ledger) == {}
    assert ledger.get_or_create("buyer").pages_used_this_cycle == 3


def test_legacy_four_column_migration_expires_unknown_ages_without_undoing_debits(tmp_path, clock):
    path = str(tmp_path / "legacy.sqlite3")
    old = PersistentLedger(path)
    old.add_credits("buyer", 50)
    original = old.charge_pages("buyer", 1)
    with old.transaction() as db:
        db.execute("INSERT INTO checkout_requests(request_key,account_id,sku,attempted_at,session_id,state) VALUES (?,?,?,?,?,?)",
                   ("purchase-key", "buyer", "pack_50", clock[0] - 10 * TTL, "cs_old", "fulfilled"))
        db.execute("INSERT INTO entitlements VALUES (?,?,?)", ("cs_old", "buyer", "pack_50"))
        db.execute("INSERT INTO webhook_events VALUES (?)", ("evt_old",))
        db.execute("DROP TABLE conversion_charges")
        db.execute("CREATE TABLE conversion_charges(request_key TEXT PRIMARY KEY, account_id TEXT NOT NULL, fingerprint TEXT NOT NULL, charge TEXT NOT NULL)")
        db.execute("INSERT INTO conversion_charges VALUES (?,?,?,?)", ("legacy-retry", "buyer", "legacy-fingerprint", json.dumps(original)))
    # Simulate API workers initializing the old schema at the same time.
    with ThreadPoolExecutor(max_workers=4) as pool:
        migrated = list(pool.map(lambda _: PersistentLedger(path), range(8)))
    current = migrated[0]
    assert records(current) == {}
    assert current.get_or_create("buyer").credits == 50
    assert current.get_or_create("buyer").pages_used_this_cycle == 1
    with closing(current.connect()) as db:
        columns = {row['name'] for row in db.execute("PRAGMA table_info(conversion_charges)")}
        assert 'created_at' in columns
        assert db.execute("SELECT request_key FROM checkout_requests").fetchone()[0] == "purchase-key"
        assert db.execute("SELECT session_id FROM entitlements").fetchone()[0] == "cs_old"
        assert db.execute("SELECT event_id FROM webhook_events").fetchone()[0] == "evt_old"
    current.charge_pages_once("buyer", 1, "legacy-retry", "different-new-payload")
    assert current.get_or_create("buyer").pages_used_this_cycle == 2
    assert records(PersistentLedger(path))['legacy-retry']['created_at'] == clock[0]


@pytest.mark.parametrize("failure", ["missing-file", "multipart", "format", "empty", "header", "parse", "quota", "writer"])
def test_every_failed_conversion_request_purges_expired_metadata(ledger, clock, monkeypatch, fixtures_dir, failure):
    ledger.charge_pages_once("old-account", 1, "expired-key", "old-fingerprint")
    clock[0] += TTL + 0.001
    # Retain a row created exactly 24 hours ago to check the strict boundary.
    ledger.charge_pages_once("boundary-account", 1, "boundary-key", "boundary-fingerprint")
    if isinstance(ledger, PersistentLedger):
        with ledger.transaction() as db:
            db.execute("UPDATE conversion_charges SET created_at=? WHERE request_key='boundary-key'", (clock[0] - TTL,))
            # The direct ledger call above purged expired rows, so reseed the
            # expired metadata to ensure HTTP request middleware removes it.
            db.execute("INSERT INTO conversion_charges VALUES (?,?,?,?,?)", ("expired-key", "old-account", "old-fingerprint", "{}", clock[0] - TTL - 0.001))
    else:
        boundary = ledger._conversion_charges['boundary-key']
        ledger._conversion_charges['boundary-key'] = (*boundary[:3], clock[0] - TTL)
        ledger._conversion_charges['expired-key'] = ("old-account", "old-fingerprint", {}, clock[0] - TTL - 0.001)
    monkeypatch.setattr(api, "LEDGER", ledger)
    data = (fixtures_dir / ("scanned_empty.pdf" if failure == "parse" else "acmebank.pdf")).read_bytes()
    if failure == "quota":
        ledger.charge_pages("request-account", 3)
    if failure == "writer":
        def fail_writer(*args):
            raise RuntimeError("synthetic writer failure")
        monkeypatch.setattr(api, "to_xlsx_bytes", fail_writer)
    with TestClient(api.app, raise_server_exceptions=False) as client:
        if failure == "missing-file":
            response = client.post("/api/convert", data={"fmt": "csv"})
            expected = 422
        elif failure == "multipart":
            response = client.post("/api/convert", content=b"malformed multipart", headers={"Content-Type": "multipart/form-data"})
            expected = 400
        else:
            response = client.post("/api/convert", files={"file": ("synthetic.pdf", b"" if failure == "empty" else data, "application/pdf")},
                                   data={"account_id": "request-account", "fmt": "bad" if failure == "format" else "xlsx"},
                                   headers={"Idempotency-Key": "short"} if failure == "header" else {})
            expected = {"format": 400, "empty": 400, "header": 400, "parse": 422, "quota": 402, "writer": 500}[failure]
        assert response.status_code == expected
    assert set(records(ledger)) == {"boundary-key"}
    assert ledger.get_or_create("old-account").pages_used_this_cycle == 1
    assert ledger.get_or_create("request-account").pages_used_this_cycle == (3 if failure == "quota" else 0)


def test_conversion_cleanup_does_not_apply_to_checkout_routes(ledger, clock, monkeypatch):
    ledger.charge_pages_once("old-account", 1, "expired-key", "old-fingerprint")
    clock[0] += TTL + 0.001
    monkeypatch.setattr(api, "LEDGER", ledger)
    with TestClient(api.app) as client:
        assert client.post("/api/checkout", json={}).status_code == 422
    assert set(records(ledger)) == {"expired-key"}


def test_waiting_for_charge_lock_across_deadline_rechecks_expiry(tmp_path, clock, monkeypatch):
    ledger = PersistentLedger(str(tmp_path / "billing.sqlite3"))
    ledger.charge_pages_once("buyer", 1, "retry-key", "payload-A")
    clock[0] += TTL
    original = ledger.transaction
    calls = [0]
    @contextmanager
    def delayed_transaction():
        with original() as db:
            calls[0] += 1
            if calls[0] == 2:
                clock[0] += 0.001  # The charge transaction obtains its lock later.
            yield db
    monkeypatch.setattr(ledger, "transaction", delayed_transaction)
    ledger.charge_pages_once("buyer", 1, "retry-key", "payload-A")
    assert ledger.get_or_create("buyer").pages_used_this_cycle == 2
    assert records(ledger)['retry-key']['created_at'] == clock[0]


def test_expiry_while_waiting_then_quota_failure_still_deletes_metadata(tmp_path, clock, monkeypatch):
    ledger = PersistentLedger(str(tmp_path / "billing.sqlite3"))
    ledger.charge_pages_once("buyer", 1, "retry-key", "payload-A")
    ledger.charge_pages("buyer", 2)
    clock[0] += TTL - 1
    original = ledger.transaction
    calls = [0]
    @contextmanager
    def delayed_transaction():
        with original() as db:
            calls[0] += 1
            if calls[0] == 2:
                clock[0] += 2  # Fresh at prepurge, expired when debit gets its lock.
            yield db
    monkeypatch.setattr(ledger, "transaction", delayed_transaction)
    with pytest.raises(InsufficientCredits):
        ledger.charge_pages_once("buyer", 1, "retry-key", "payload-A")
    assert ledger.get_or_create("buyer").pages_used_this_cycle == 3
    assert records(ledger) == {}


def test_lock_wait_then_conflicting_lookup_commits_unrelated_expiry(tmp_path, clock, monkeypatch):
    ledger = PersistentLedger(str(tmp_path / "billing.sqlite3"))
    ledger.charge_pages_once("old", 1, "expired-key", "payload-A")
    clock[0] += TTL / 2
    ledger.charge_pages_once("buyer", 1, "fresh-key", "payload-B")
    clock[0] += TTL / 2 - 1
    original = ledger.transaction
    calls = [0]
    @contextmanager
    def delayed_transaction():
        with original() as db:
            calls[0] += 1
            if calls[0] == 2:
                clock[0] += 2
            yield db
    monkeypatch.setattr(ledger, "transaction", delayed_transaction)
    with pytest.raises(ValueError, match="another conversion"):
        ledger.conversion_charge("buyer", "fresh-key", "different-payload")
    assert set(records(ledger)) == {'fresh-key'}
    assert ledger.get_or_create("buyer").pages_used_this_cycle == 1
    assert ledger.get_or_create("old").pages_used_this_cycle == 1
