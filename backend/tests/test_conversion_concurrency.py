"""Health and conversion share one ASGI loop, including during slow PDF work.

The watchdog only releases a broken implementation so the test cannot hang.
Correctness is the order of events, rather than a conversion latency target.
"""

import asyncio
import threading

import httpx
import pytest

import statement_to_excel.api as api
from statement_to_excel.billing import PersistentLedger, StripeBillingProvider


@pytest.mark.parametrize(
    ("phase", "fmt"),
    [
        ("_count_pages", "json"),
        ("convert_pdf", "json"),
        ("to_csv_bytes", "csv"),
        ("to_xlsx_bytes", "xlsx"),
        ("JSONResponse", "json"),
    ],
    ids=["page-count", "transaction-parse", "csv-writer", "xlsx-writer", "json-serialization"],
)
def test_health_responds_on_same_asgi_loop_while_conversion_phase_is_blocked(
    monkeypatch, tmp_path, fixtures_dir, phase, fmt
):
    monkeypatch.setattr(api, "LEDGER", PersistentLedger(str(tmp_path / "billing.sqlite3")))
    monkeypatch.setattr(api, "PROVIDER", StripeBillingProvider(secret_key="", webhook_secret=""))
    original = getattr(api, phase)
    entered = threading.Event()
    release = threading.Event()
    watchdog_released = threading.Event()
    events = []
    phase_threads = []

    def blocked_phase(*args, **kwargs):
        phase_threads.append(threading.get_ident())
        events.append("phase-entered")
        entered.set()
        # This bounded wait also unblocks the old handler when it incorrectly
        # calls this synchronous function directly on the ASGI event loop.
        if not release.wait(timeout=5):
            watchdog_released.set()
        events.append("phase-released")
        return original(*args, **kwargs)

    monkeypatch.setattr(api, phase, blocked_phase)
    pdf = (fixtures_dir / "acmebank.pdf").read_bytes()

    async def exercise_same_loop():
        loop_thread = threading.get_ident()
        transport = httpx.ASGITransport(app=api.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            conversion = asyncio.create_task(client.post(
                "/api/convert",
                files={"file": ("synthetic.pdf", pdf, "application/pdf")},
                data={"fmt": fmt, "account_id": "concurrent-synthetic-account"},
            ))
            try:
                # Waiting for the worker's event happens off the ASGI loop too.
                assert await asyncio.to_thread(entered.wait, 10), "conversion phase was never reached"
                health = await asyncio.wait_for(client.get("/api/health"), timeout=10)
                events.append("health-returned")
                assert health.status_code == 200
                assert health.json()["status"] == "ok"
            finally:
                # Release on every assertion/error path, then await the request
                # before the client, event loop, or monkeypatches are torn down.
                release.set()
                response = await asyncio.wait_for(conversion, timeout=10)
            assert response.status_code == 200, response.text
            return loop_thread

    loop_thread = asyncio.run(exercise_same_loop())
    assert events.index("health-returned") < events.index("phase-released"), (
        f"{phase} blocked the ASGI loop; event order was {events}"
    )
    assert not watchdog_released.is_set(), "the watchdog had to release conversion before health responded"
    assert len(phase_threads) == 1
    assert phase_threads[0] != loop_thread, f"{phase} ran on the ASGI event-loop thread"
