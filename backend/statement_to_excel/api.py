"""FastAPI application: upload a statement PDF, get back a spreadsheet.

Endpoints
---------
``GET  /api/health``                  liveness probe
``GET  /api/pricing``                 plan + credit-pack catalog (shared w/ UI)
``GET  /api/account/{id}``            metering state for an account
``POST /api/account/{id}/quote``      cost of processing N pages (no charge)
``POST /api/checkout``                idempotent Stripe test Checkout
``GET  /api/checkout/{sid}``          account-bound payment status
``POST /api/stripe/webhook``          signed payment -> exactly-once entitlement
``POST /api/convert``                 multipart PDF upload -> metered conversion

Conversion and output generation run locally in memory. Usage is charged only
after successful output generation. Optional Idempotency-Key prevents repeat
usage debits for 24 hours after creation; replay does not extend that window.
Billing stores metadata only. Until Stripe test Checkout and signed webhooks are
configured, conversions are unmetered and write no account or conversion records.
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
from typing import Annotated, Optional

from anyio import CancelScope
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartParser

from . import __version__
from .billing import (
    BillingError, InsufficientCredits, PersistentLedger, PRICING, StripeBillingProvider,
    apply_webhook, checkout_status, create_checkout, get_provider,
)
from .engine import ConversionError, convert_pdf, summarize
from .writers import to_csv_bytes, to_xlsx_bytes

# SQLite persists billing and metering metadata only. Uploads and converted
# transaction rows must never enter the ledger or provider.
LEDGER = PersistentLedger(os.getenv("STX_BILLING_DATABASE", "var/billing.sqlite3"))
PROVIDER = get_provider()

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_STATEMENT_PAGES = 100
# Starlette's file parser uses this supported class setting when it constructs
# SpooledTemporaryFile. Keep every accepted PDF in memory; oversized rejected
# uploads can still spill and are closed/deleted by the cleanup below.
MultiPartParser.spool_max_size = MAX_UPLOAD_BYTES + 1024 * 1024

app = FastAPI(title="statement-to-excel", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def purge_conversion_retry_metadata(request: Request, call_next):
    """Clean conversion metadata even when multipart/schema validation fails."""
    if request.method == "POST" and request.url.path == "/api/convert":
        await run_in_threadpool(LEDGER.purge_conversion_charges)
    return await call_next(request)


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class QuoteRequest(BaseModel):
    pages: int


class CheckoutRequest(BaseModel):
    account_id: str
    sku: str


def checkout_available() -> bool:
    """Only a configured Stripe test provider enables checkout and metering."""
    return isinstance(PROVIDER, StripeBillingProvider) and PROVIDER.checkout_available


def _account_view(account_id: str) -> dict:
    acct = LEDGER.get_or_create(account_id) if checkout_available() else LEDGER.get_if_exists(account_id)
    return {
        "id": acct.id,
        "plan": acct.plan_id,
        "credits": acct.credits,
        "included_pages": acct.plan.included_pages,
        "pages_used_this_cycle": acct.pages_used_this_cycle,
        "included_remaining": acct.included_remaining(),
        "pro": acct.pro,
    }


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "billing": PROVIDER.name,
            "checkout_available": checkout_available()}


@app.get("/api/pricing")
def pricing() -> dict:
    return {**PRICING, "checkout_available": checkout_available()}


@app.get("/api/account/{account_id}")
def get_account(account_id: str) -> dict:
    return _account_view(account_id)


@app.post("/api/account/{account_id}/quote")
def quote(account_id: str, body: QuoteRequest) -> dict:
    if body.pages < 0:
        raise HTTPException(status_code=400, detail="pages must be >= 0")
    if not checkout_available():
        return {"pages": body.pages, "metered": False, "sufficient": True}
    acct = LEDGER.get_or_create(account_id)
    return acct.quote(body.pages)


@app.post("/api/checkout")
def checkout(body: CheckoutRequest, idempotency_key: str = Header("")) -> dict:
    if not checkout_available():
        raise HTTPException(status_code=503, detail="Checkout is unavailable until Stripe test credentials and webhook are configured.")
    try:
        return create_checkout(LEDGER, PROVIDER, body.account_id, body.sku, idempotency_key)
    except BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header("")) -> dict:
    if not checkout_available():
        raise HTTPException(status_code=503, detail="Stripe test checkout and webhook must be configured before payments can be fulfilled.")
    try:
        event = PROVIDER.verify_event(await request.body(), stripe_signature)
        return apply_webhook(LEDGER, event)
    except BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/api/checkout/{session_id}")
def get_checkout_status(session_id: str, account_id: str) -> dict:
    try:
        return checkout_status(LEDGER, session_id, account_id)
    except BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _count_pages(data: bytes) -> int:
    """Count page metadata, stopping at the first page beyond the limit.

    Password/format failures are left to the converter's existing clear 422
    errors. Iterate pdfminer's page metadata directly: pdfplumber.close() would
    materialize the entire page list, defeating an early bounded count.
    """
    try:
        from pdfminer.pdfpage import PDFPage

        with io.BytesIO(data) as stream:
            pages = sum(1 for _ in PDFPage.get_pages(stream, maxpages=MAX_STATEMENT_PAGES + 1))
        return max(1, pages)
    except Exception:
        return 1


def _convert_response(
    data: bytes,
    account_id: str,
    fmt: str,
    currency: str,
    preview: bool,
    idempotency_key: Optional[str],
    metered: bool,
    ledger,
) -> Response:
    """Run PDF work, output encoding and metering entirely in a worker thread."""
    pages = _count_pages(data)
    if pages > MAX_STATEMENT_PAGES:
        raise HTTPException(status_code=413, detail="PDF statements are limited to 100 pages")

    # Parse first; only charge on success.
    try:
        txns = convert_pdf(io.BytesIO(data), currency=currency)
    except ConversionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    summary = summarize(txns).to_dict()
    reconciliation = txns.reconciliation.to_dict()
    layout = txns.layout
    # Finish serialization first: failed output generation must not spend pages.
    if fmt == "json":
        body = None
        media = "application/json"
    elif fmt == "csv":
        body = to_csv_bytes(txns)
        media = "text/csv"
    else:
        body = to_xlsx_bytes(txns)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ext = fmt

    charge = {"metered": False, "pages": pages}
    if metered:
        try:
            if idempotency_key:
                fingerprint = hashlib.sha256(data + b"\0" + fmt.encode() + b"\0" + currency.encode()).hexdigest()
                charge = ledger.charge_pages_once(account_id, pages, idempotency_key, fingerprint)
            else:
                charge = ledger.charge_pages(account_id, pages)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except InsufficientCredits as exc:
            acct = ledger.get_or_create(account_id)
            return JSONResponse(status_code=402, content={
                "error": "insufficient_credits", "detail": str(exc), "quote": acct.quote(pages),
            })

    if fmt == "json":
        return JSONResponse(content={
            "transactions": [t.to_dict() for t in txns],
            "summary": summary, "charge": charge,
            "reconciliation": reconciliation, "layout": layout,
        })

    if preview:
        return JSONResponse(
            content={
                "transactions": [t.to_dict() for t in txns],
                "summary": summary,
                "reconciliation": reconciliation,
                "layout": layout,
                "charge": charge,
                "file_b64": base64.b64encode(body).decode("ascii"),
                "filename": f"statement.{ext}",
                "media_type": media,
            }
        )

    headers = {
        "Content-Disposition": f'attachment; filename="statement.{ext}"',
        "X-Transaction-Count": str(summary["count"]),
    }
    if metered:
        headers["X-Credits-Remaining"] = str(charge["credits_after"])
    return Response(content=body, media_type=media, headers=headers)


@app.post("/api/convert")
async def convert(
    file: UploadFile = File(...),
    account_id: str = Form("anon"),
    fmt: str = Form("xlsx"),
    currency: str = Form("USD"),
    preview: bool = Form(False),
    idempotency_key: Annotated[Optional[str], Header()] = None,
) -> Response:
    """Metered conversion. With ``preview`` set (and a binary ``fmt``), the
    response is JSON carrying both the parsed rows *and* the file
    base64-inline, so a UI can show the preview table and offer the download
    from one call — charging the account once instead of twice."""
    try:
        metered = checkout_available()
        fmt = (fmt or "xlsx").lower()
        if fmt not in {"xlsx", "csv", "json"}:
            raise HTTPException(status_code=400, detail="fmt must be xlsx|csv|json")

        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="PDF uploads are limited to 20 MiB")
        if not data:
            raise HTTPException(status_code=400, detail="empty upload")

        if idempotency_key is not None and not 16 <= len(idempotency_key) <= 200:
            raise HTTPException(status_code=400, detail="Idempotency-Key must be 16 to 200 characters")
        return await run_in_threadpool(
            _convert_response, data, account_id, fmt, currency, preview,
            idempotency_key, metered, LEDGER,
        )
    finally:
        # Closing releases memory and deletes rejected or forced disk spills.
        # Shield the worker-thread close so cancellation cannot skip cleanup.
        with CancelScope(shield=True):
            await file.close()


def create_app() -> FastAPI:
    """Factory for ASGI servers (``uvicorn --factory statement_to_excel.api:create_app``)."""
    return app
