"""Real multipart uploads stay in memory and PDF limits precede conversion.

Every document is generated from fictional transactions. Padding consists of
legal PDF comments inserted after the cross-reference/trailer and before the
final startxref marker; original object offsets and the xref offset stay valid.
"""

from contextlib import closing
from io import BytesIO
import csv
import tempfile
import sys

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
import starlette.formparsers as formparsers

import statement_to_excel.api as api
import statement_to_excel.conversion as conversion
import statement_to_excel.conversion_timeout as deadline
from statement_to_excel.billing import PersistentLedger, StripeBillingProvider


MIB = 1024 * 1024
ACCOUNT = "synthetic-upload-limits"
TABLES = ("accounts", "conversion_charges", "checkout_requests", "checkout_aliases",
          "entitlements", "webhook_events", "subscription_state")


def _statement(pages=1, *, exact_bytes=None):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(612, 792), invariant=1, pageCompression=1)
    expected = []
    for page in range(1, pages + 1):
        pdf.drawString(40, 750, "SYNTHETIC TEST STATEMENT - January 2024")
        pdf.drawString(40, 730, "Account ending 0000")
        pdf.drawString(40, 710, "Date Description Amount Balance")
        pdf.drawString(40, 680, f"01/02/2024 SYNTHETIC DEPOSIT #{page} 1.00 {page:.2f}")
        pdf.drawString(40, 25, f"Page {page} of {pages} - fictional test data")
        pdf.showPage()
        expected.append({
            "date": "2024-01-02", "description": f"SYNTHETIC DEPOSIT #{page}",
            "amount": "1.00", "balance": f"{page:.2f}",
            "currency": "USD", "type": "credit",
        })
    pdf.save()
    data = buffer.getvalue()
    if exact_bytes is not None:
        count = exact_bytes - len(data)
        assert count > 0, "Synthetic PDF is already larger than requested padding size"
        comment = b"% legal synthetic padding; no customer data " + b"x" * 34 + b"\n"
        repetitions, remainder = divmod(count, len(comment))
        padding = comment * repetitions
        if remainder == 1:
            padding += b"\n"
        elif remainder:
            padding += b"%" + b"x" * (remainder - 2) + b"\n"
        index = data.rindex(b"startxref\n")
        data = data[:index] + padding + data[index:]
        assert len(data) == exact_bytes
    return data, expected


@pytest.fixture(params=[False, True], ids=["unconfigured", "configured-test-checkout"])
def conversion_client(request, monkeypatch, tmp_path):
    metered = request.param
    ledger = PersistentLedger(str(tmp_path / "billing.sqlite3"))
    monkeypatch.setattr(api, "LEDGER", ledger)
    provider = StripeBillingProvider(
        secret_key="sk_test_synthetic_not_a_credential" if metered else "",
        webhook_secret="whsec_synthetic_not_a_credential" if metered else "",
        portal_configuration="bpc_synthetic" if metered else "",
    )
    monkeypatch.setattr(api, "PROVIDER", provider)
    # Neither mode in these tests is permitted to open an external checkout.
    import stripe
    def forbidden_checkout(*args, **kwargs):
        raise AssertionError("Upload limit tests must never contact Stripe")
    monkeypatch.setattr(stripe.checkout.Session, "create", forbidden_checkout)
    with TestClient(api.app) as client:
        yield client, ledger, metered


def _snapshot(ledger):
    with closing(ledger.connect()) as db:
        return {table: [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1")]
                for table in TABLES}


def _reject_disk_spooling(monkeypatch):
    """Observe the actual Starlette constructor, rollover, and disk allocator."""
    spools, rollovers, disk_allocations = [], [], []
    original_spool = formparsers.SpooledTemporaryFile
    original_rollover = tempfile.SpooledTemporaryFile.rollover

    def tracked_spool(*args, **kwargs):
        spool = original_spool(*args, **kwargs)
        spools.append(spool)
        return spool

    def tracked_rollover(spool):
        rollovers.append(spool)
        return original_rollover(spool)

    def forbidden_disk_file(*args, **kwargs):
        disk_allocations.append(True)
        raise AssertionError("An accepted multipart PDF must never create a temporary disk file")

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", tracked_spool)
    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "rollover", tracked_rollover)
    monkeypatch.setattr(tempfile, "TemporaryFile", forbidden_disk_file)
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", forbidden_disk_file)
    # openpyxl imports its allocator directly, so patching only tempfile would
    # miss worksheet XML spilled by the Excel export implementation.
    import openpyxl.worksheet._writer as worksheet_writer
    monkeypatch.setattr(worksheet_writer, "NamedTemporaryFile", forbidden_disk_file)
    monkeypatch.setattr(worksheet_writer, "create_temporary_file", forbidden_disk_file)
    return spools, rollovers, disk_allocations


@pytest.mark.parametrize(("size", "fmt"), [
    pytest.param(5 * MIB, "json", id="5-MiB-json"),
    pytest.param(5 * MIB, "csv", id="5-MiB-csv"),
    pytest.param(5 * MIB, "xlsx", id="5-MiB-xlsx"),
    pytest.param(20 * MIB, "json", id="20-MiB-exact-boundary"),
])
def test_valid_large_multipart_pdf_converts_without_a_temporary_disk_file(
    conversion_client, monkeypatch, size, fmt,
):
    client, ledger, metered = conversion_client
    data, expected = _statement(exact_bytes=size)
    spools, rollovers, disk_allocations = _reject_disk_spooling(monkeypatch)
    # Exec workers do not inherit parent monkeypatches. Install the same disk
    # allocator guards inside the actual child for the accepted upload path.
    monkeypatch.setattr(deadline, "_worker_command", lambda: [
        sys.executable, "-m", "tests.deadline_worker", "no_disk", "0",
    ])
    response = client.post("/api/convert", files={
        "file": ("synthetic-padded.pdf", data, "application/pdf"),
    }, data={"account_id": ACCOUNT, "fmt": fmt})
    assert response.status_code == 200, response.text
    if fmt == "json":
        assert response.json()["transactions"] == expected
        assert response.json()["charge"]["pages"] == 1
    elif fmt == "csv":
        assert list(csv.DictReader(response.text.splitlines())) == expected
        assert response.headers["X-Transaction-Count"] == "1"
    else:
        from openpyxl import load_workbook
        workbook = load_workbook(BytesIO(response.content), data_only=True)
        try:
            rows = list(workbook["Transactions"].values)
            assert len(rows) == 2
            assert rows[1][0].isoformat().startswith("2024-01-02")
            assert rows[1][1:] == ("SYNTHETIC DEPOSIT #1", 1, 1, "USD", "credit")
            assert dict(workbook["Summary"].values)["Transactions"] == 1
        finally:
            workbook.close()
        assert response.headers["X-Transaction-Count"] == "1"
    assert len(spools) == 1, "Test must exercise the real multipart upload parser"
    assert all(spool.closed and not spool._rolled for spool in spools)
    assert rollovers == disk_allocations == []
    state = _snapshot(ledger)
    if metered:
        assert state["accounts"][0]["pages_used"] == 1
    else:
        if fmt == "json":
            assert response.json()["charge"] == {"metered": False, "pages": 1}
        assert all(rows == [] for rows in state.values())


def test_more_than_20_mib_rejected_before_pdf_conversion_without_disk_or_charge(
    conversion_client, monkeypatch,
):
    client, ledger, _ = conversion_client
    data, _ = _statement(exact_bytes=20 * MIB + 1)
    before = _snapshot(ledger)
    spools, rollovers, disk_allocations = _reject_disk_spooling(monkeypatch)
    async def forbidden_parse(*args, **kwargs):
        raise AssertionError("An oversized PDF must be rejected before the conversion worker")
    monkeypatch.setattr(api, "run_conversion", forbidden_parse)
    response = client.post("/api/convert", files={
        "file": ("synthetic-over-limit.pdf", data, "application/pdf"),
    }, data={"account_id": ACCOUNT, "fmt": "json"},
       headers={"Idempotency-Key": "synthetic-upload-over-limit-key"})
    assert response.status_code == 413, response.text
    assert "20 MiB" in response.json()["detail"]
    assert len(spools) == 1 and all(spool.closed and not spool._rolled for spool in spools)
    assert rollovers == disk_allocations == []
    assert _snapshot(ledger) == before


def test_exactly_100_page_pdf_preserves_independent_ground_truth(conversion_client):
    client, ledger, metered = conversion_client
    if metered:
        ledger.add_credits(ACCOUNT, 100)
    data, expected = _statement(pages=100)
    response = client.post("/api/convert", files={
        "file": ("synthetic-100-pages.pdf", data, "application/pdf"),
    }, data={"account_id": ACCOUNT, "fmt": "json"},
       headers={"Idempotency-Key": "synthetic-100-pages-request-key"})
    assert response.status_code == 200, response.text
    assert response.json()["transactions"] == expected
    assert response.json()["summary"]["count"] == 100
    assert response.json()["charge"]["pages"] == 100
    if metered:
        state = _snapshot(ledger)
        assert state["accounts"][0]["pages_used"] == 3
        assert state["accounts"][0]["credits"] == 3
        assert len(state["conversion_charges"]) == 1
    else:
        assert response.json()["charge"] == {"metered": False, "pages": 100}
        assert all(rows == [] for rows in _snapshot(ledger).values())


def test_101_page_pdf_rejected_before_transaction_conversion_and_never_charged(
    conversion_client, monkeypatch,
):
    client, ledger, metered = conversion_client
    if metered:
        ledger.add_credits(ACCOUNT, 200)
    data, _ = _statement(pages=101)
    before = _snapshot(ledger)
    def forbidden_parse(*args, **kwargs):
        raise AssertionError("More than 100 PDF pages must be rejected before transaction conversion")
    # Verify the page-count guard independently of the subprocess boundary.
    monkeypatch.setattr(conversion, "convert_pdf", forbidden_parse)
    with pytest.raises(conversion.ConversionRejected) as rejected:
        conversion.prepare_conversion(data, "json", "USD", False)
    assert rejected.value.status_code == 413
    response = client.post("/api/convert", files={
        "file": ("synthetic-101-pages.pdf", data, "application/pdf"),
    }, data={"account_id": ACCOUNT, "fmt": "json"},
       headers={"Idempotency-Key": "synthetic-101-pages-request-key"})
    assert response.status_code == 413, response.text
    assert "100 pages" in response.json()["detail"]
    assert _snapshot(ledger) == before
