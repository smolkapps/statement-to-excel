"""Busy conversions retain bounded capacity while health stays responsive."""

import asyncio
import threading

import httpx
import pytest

import statement_to_excel.api as api
import statement_to_excel.conversion_timeout as deadline
from statement_to_excel.billing import Ledger, StripeBillingProvider
from tests.deadline_support import WorkerProbe


def test_busy_limit_health_and_recovery_wait_for_worker_cleanup(monkeypatch, fixtures_dir):
    ledger = Ledger()
    monkeypatch.setattr(api, "LEDGER", ledger)
    monkeypatch.setattr(api, "PROVIDER", StripeBillingProvider("", ""))
    original_command = deadline._worker_command
    data = (fixtures_dir / "acmebank.pdf").read_bytes()

    async def exercise():
        transport = httpx.ASGITransport(app=api.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            async def request():
                return await client.post("/api/convert", files={"file": ("synthetic.pdf", data, "application/pdf")},
                                         data={"fmt": "json", "account_id": "busy"})

            async with WorkerProbe(monkeypatch, "parse", timeout=10) as probe:
                requests = [asyncio.create_task(request()) for _ in range(deadline.MAX_CONCURRENT_CONVERSIONS)]
                try:
                    for _ in requests:
                        await probe.wait_entered()
                    health, busy = await asyncio.wait_for(asyncio.gather(
                        client.get("/api/health"), request(),
                    ), timeout=1)
                    assert health.status_code == 200
                    assert busy.status_code == 503 and "try again" in busy.json()["detail"].lower()
                    assert all(not task.done() for task in requests)
                    assert len(probe.processes) == deadline.MAX_CONCURRENT_CONVERSIONS
                finally:
                    for task in requests:
                        task.cancel()
                    await asyncio.gather(*requests, return_exceptions=True)
                probe.assert_reaped()
                assert ledger.accounts == {} and ledger._conversion_charges == {}
            monkeypatch.setattr(deadline, "_worker_command", original_command)
            monkeypatch.setattr(deadline, "CONVERSION_TIMEOUT_SECONDS", 30)
            subsequent = await request()
            assert subsequent.status_code == 200, subsequent.text
            assert subsequent.json()["summary"]["count"] == 5

    asyncio.run(exercise())


@pytest.mark.parametrize("cancel_parent", [False, True], ids=["billing-wait", "cancel-during-billing"])
def test_admission_remains_bounded_until_parent_billing_finishes(
    monkeypatch, fixtures_dir, configured_provider, cancel_parent,
):
    """Completed artifacts cannot accumulate behind a slow metadata database."""
    ledger = Ledger()
    monkeypatch.setattr(api, "LEDGER", ledger)
    original_charge = ledger.charge_pages_once
    release = threading.Event()
    both_billing = threading.Event()
    counter_lock = threading.Lock()
    entered = []

    def blocked_charge(*args):
        with counter_lock:
            entered.append(args[2])
            if len(entered) == 2:
                both_billing.set()
        assert release.wait(10), "test watchdog released a blocked billing operation"
        return original_charge(*args)

    monkeypatch.setattr(ledger, "charge_pages_once", blocked_charge)
    data = (fixtures_dir / "acmebank.pdf").read_bytes()

    async def exercise():
        transport = httpx.ASGITransport(app=api.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            async def request(number):
                return await client.post("/api/convert", files={"file": ("synthetic.pdf", data, "application/pdf")},
                                         data={"fmt": "json", "account_id": "slow-billing"},
                                         headers={"Idempotency-Key": f"synthetic-billing-operation-{number:04d}"})

            async with WorkerProbe(monkeypatch, "no_disk", timeout=5) as probe:
                requests = [asyncio.create_task(request(number)) for number in range(2)]
                try:
                    assert await asyncio.wait_for(asyncio.to_thread(both_billing.wait, 8), timeout=9)
                    probe.assert_reaped()
                    if cancel_parent:
                        requests[0].cancel()
                        await asyncio.sleep(0)
                    health, busy = await asyncio.wait_for(asyncio.gather(
                        client.get("/api/health"), request(2),
                    ), timeout=1)
                    assert health.status_code == 200
                    assert busy.status_code == 503
                    assert all(not task.done() for task in requests), "billing still owns both conversion slots"
                    assert len(probe.processes) == 2, "busy requests must not spawn another document worker"
                finally:
                    release.set()
                    responses = await asyncio.gather(*requests, return_exceptions=True)
                if cancel_parent:
                    assert isinstance(responses[0], asyncio.CancelledError)
                else:
                    assert responses[0].status_code == 200
                assert responses[1].status_code == 200
                assert ledger.accounts["slow-billing"].pages_used_this_cycle == 2
                retry = await request(0)
                assert retry.status_code == 200
                assert ledger.accounts["slow-billing"].pages_used_this_cycle == 2
                subsequent = await request(2)
                assert subsequent.status_code == 200
                assert ledger.accounts["slow-billing"].pages_used_this_cycle == 3

    try:
        asyncio.run(exercise())
    finally:
        release.set()
