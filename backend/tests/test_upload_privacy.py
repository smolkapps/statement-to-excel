"""Uploaded statements must be released before conversion returns, even on errors."""

import asyncio
import os
import tempfile

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

import statement_to_excel.api as api
from statement_to_excel.conversion_timeout import ConversionWorkerError
from statement_to_excel.billing import Ledger, StripeBillingProvider


@pytest.mark.parametrize("outcome", ["success", "parse", "format", "empty", "quota", "writer", "oversize"])
@pytest.mark.parametrize("metered", [False, True])
def test_spooled_upload_deleted_before_endpoint_returns(monkeypatch, fixtures_dir, tmp_path, outcome, metered, configured_provider):
    ledger = Ledger()
    monkeypatch.setattr(api, "LEDGER", ledger)
    if not metered:
        monkeypatch.setattr(api, "PROVIDER", StripeBillingProvider(secret_key="", webhook_secret=""))
    data = (fixtures_dir / ("scanned_empty.pdf" if outcome == "parse" else "acmebank.pdf")).read_bytes()
    if outcome == "empty":
        data = b""
    if outcome == "oversize":
        data = b"%PDF-" + b"x" * (20 * 1024 * 1024)
    if outcome == "quota":
        for _ in range(3):
            ledger.charge_pages("privacy", 1)
    if outcome == "writer":
        async def broken_writer(*args):
            raise ConversionWorkerError()
        monkeypatch.setattr(api, "run_conversion", broken_writer)
    spool = tempfile.SpooledTemporaryFile(max_size=1, mode="w+b", dir=tmp_path)
    spool.write(data)
    spool.rollover()  # Exercise the real on-disk multipart spill path, including empty input.
    fd = spool.fileno()
    spool.seek(0)
    upload = UploadFile(file=spool, filename="synthetic.pdf")
    kwargs = dict(file=upload, account_id="privacy", fmt="bad" if outcome == "format" else "xlsx", currency="USD", preview=False)
    try:
        if outcome in {"parse", "format", "empty", "oversize"}:
            with pytest.raises(HTTPException) as failure:
                asyncio.run(api.convert(**kwargs))
            if outcome == "oversize":
                assert failure.value.status_code == 413
        elif outcome == "writer":
            with pytest.raises(HTTPException) as failure:
                asyncio.run(api.convert(**kwargs))
            assert failure.value.status_code == 500
        else:
            response = asyncio.run(api.convert(**kwargs))
            assert response.status_code == (402 if outcome == "quota" and metered else 200)
        assert spool.closed, "upload must close immediately, before the endpoint returns"
        with pytest.raises(OSError):
            os.fstat(fd)
        assert list(tmp_path.iterdir()) == [], "no uploaded statement may remain on disk"
    finally:
        spool.close()


def test_real_multipart_spills_are_closed_and_deleted(monkeypatch, fixtures_dir, tmp_path):
    import starlette.formparsers as formparsers
    records = []
    original = tempfile.SpooledTemporaryFile
    def tracked_spool(*args, **kwargs):
        kwargs.update(max_size=1, dir=tmp_path)
        spool = original(*args, **kwargs)
        records.append(spool)
        return spool
    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", tracked_spool)
    monkeypatch.setattr(api, "LEDGER", Ledger())
    with TestClient(api.app) as client:
        for filename in ["acmebank.pdf", "scanned_empty.pdf"]:
            response = client.post("/api/convert", files={"file": (filename, (fixtures_dir / filename).read_bytes(), "application/pdf")}, data={"account_id": "multipart", "fmt": "csv"})
            assert response.status_code == (422 if filename.startswith("scanned") else 200)
    assert len(records) == 2
    assert all(spool._rolled and spool.closed for spool in records)
    assert list(tmp_path.iterdir()) == []
