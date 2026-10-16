"""FastAPI application: upload a statement PDF, get back a spreadsheet.

Endpoints
---------
``GET  /api/health``                  liveness probe
``GET  /api/pricing``                 plan + credit-pack catalog (shared w/ UI)
``GET  /api/account/{id}``            metering state for an account
``POST /api/account/{id}/quote``      cost of processing N pages (no charge)
``POST /api/checkout``                idempotent owned Stripe Checkout
``GET  /api/checkout/{sid}``          account-bound payment status
``POST /api/stripe/webhook``          signed payment -> exactly-once entitlement
``POST /api/convert``                 multipart PDF upload -> metered conversion

Conversion and output generation run in a deadline-limited subprocess using
memory-only pipes. Usage is charged only
after successful output generation. Optional Idempotency-Key prevents repeat
usage debits for 24 hours after creation; replay does not extend that window.
Billing stores metadata only. Until mode-matched Stripe Checkout and signed webhooks are
configured, conversions are unmetered and write no account or conversion records.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
from contextlib import asynccontextmanager
from typing import Annotated, Optional

from anyio import CancelScope
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartParser

from . import __version__
from .billing import (
    BillingError, InsufficientCredits, PersistentLedger, PRICING, StripeBillingProvider,
    apply_webhook, checkout_status, create_checkout, create_portal, get_provider,
)
from .conversion import MAX_UPLOAD_BYTES, MAX_STATEMENT_PAGES, ConversionArtifact, ConversionRejected
from .conversion_timeout import MAX_CONCURRENT_CONVERSIONS, ConversionBusy, run_conversion
from .payments import drain_actions

# SQLite persists billing and metering metadata only. Uploads and converted
# transaction rows must never enter the ledger or provider.
PROVIDER = get_provider()
LEDGER = PersistentLedger(os.getenv("STX_BILLING_DATABASE", "var/billing.sqlite3"), mode=PROVIDER.mode)
_admission = threading.BoundedSemaphore(MAX_CONCURRENT_CONVERSIONS)

# Starlette's file parser uses this supported class setting when it constructs
# SpooledTemporaryFile. Keep every accepted PDF in memory; oversized rejected
# uploads can still spill and are closed/deleted by the cleanup below.
MultiPartParser.spool_max_size = MAX_UPLOAD_BYTES + 1024 * 1024

@asynccontextmanager
async def lifespan(app):
    async def retry_cancellations():
        while True:
            try:
                if checkout_available() and isinstance(LEDGER, PersistentLedger):
                    await run_in_threadpool(drain_actions, LEDGER, PROVIDER)
            except Exception:
                # Durable pending actions survive restart; no provider details
                # enter logs. Retry independent of another customer request.
                pass
            await asyncio.sleep(30)
    task = asyncio.create_task(retry_cancellations())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="statement-to-excel", version=__version__, lifespan=lifespan)
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
    model_config = ConfigDict(extra="forbid")
    account_id: str
    sku: str


class AccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str


class CheckoutStatusRequest(AccountRequest):
    session_id: str


def checkout_available() -> bool:
    """Only a fully configured, mode-matched provider enables metering."""
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
        "billing_hold": acct.billing_hold,
        "management_available": bool(getattr(PROVIDER, 'portal_configuration', '')) and bool(getattr(LEDGER, 'has_customer', lambda _: False)(account_id)),
    }


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__, "billing": PROVIDER.name,
            "checkout_available": checkout_available(), "billing_mode": getattr(PROVIDER, 'mode', 'test')}


@app.get("/api/pricing")
def pricing() -> dict:
    return {**PRICING, "checkout_available": checkout_available(), "billing_mode": getattr(PROVIDER, 'mode', 'test')}


@app.post("/api/account")
def account_private(body: AccountRequest) -> dict:
    return _account_view(body.account_id)


@app.post("/api/checkout/status")
def checkout_status_private(body: CheckoutStatusRequest) -> dict:
    return get_checkout_status(body.session_id, body.account_id)


@app.post("/api/billing/portal")
def billing_portal(body: AccountRequest) -> dict:
    if not checkout_available():
        raise HTTPException(status_code=503, detail="Checkout is unavailable.")
    try:
        return create_portal(LEDGER, PROVIDER, body.account_id)
    except BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


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
        raise HTTPException(status_code=503, detail="Checkout is unavailable until matching Stripe credentials and webhook are configured.")
    try:
        return create_checkout(LEDGER, PROVIDER, body.account_id, body.sku, idempotency_key)
    except BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header("")) -> dict:
    if not checkout_available():
        raise HTTPException(status_code=503, detail="Stripe checkout and webhook must be configured before payments can be fulfilled.")
    try:
        event = PROVIDER.verify_event(await request.body(), stripe_signature)
        return await run_in_threadpool(apply_webhook, LEDGER, event, PROVIDER)
    except BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/api/checkout/{session_id}")
def get_checkout_status(session_id: str, account_id: str) -> dict:
    try:
        return checkout_status(LEDGER, session_id, account_id)
    except BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _convert_response(
    artifact: ConversionArtifact,
    data: bytes,
    account_id: str,
    fmt: str,
    currency: str,
    idempotency_key: Optional[str],
    metered: bool,
    ledger,
) -> Response:
    """Commit usage only after the killable worker completely finishes output."""
    pages = artifact.pages
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
            if acct.billing_hold:
                return JSONResponse(status_code=409, content={
                    "error": "billing_hold", "detail": "Payment reconciliation is needed. Contact the site owner.",
                })
            return JSONResponse(status_code=402, content={
                "error": "insufficient_credits", "detail": str(exc), "quote": acct.quote(pages),
            })

    if artifact.media_type == "application/json":
        # The child already serialized every transaction/preview byte. Only the
        # small billing envelope remains; never re-run document work after debit.
        charge_json = json.dumps(charge, separators=(",", ":")).encode("utf-8")
        body = b'{"charge":' + charge_json + b"," + artifact.body[1:]
        return Response(content=body, media_type="application/json")

    headers = {
        "Content-Disposition": f'attachment; filename="statement.{fmt}"',
        "X-Transaction-Count": str(artifact.transaction_count),
    }
    if metered:
        headers["X-Credits-Remaining"] = str(charge["credits_after"])
    return Response(content=artifact.body, media_type=artifact.media_type, headers=headers)


async def _finish_response(*args) -> Response:
    """Keep admission until the small parent commit finishes, even on disconnect.

    Once successful document work reaches billing, existing idempotency governs
    a lost response. Cancelling a request must not leave an untracked billing
    thread holding document bytes after its admission slot was released.
    """
    cancelled = False
    with CancelScope(shield=True):
        finalizer = asyncio.create_task(run_in_threadpool(_convert_response, *args))
        while not finalizer.done():
            try:
                await asyncio.shield(finalizer)
            except asyncio.CancelledError:
                cancelled = True
        response = finalizer.result()
    if cancelled:
        raise asyncio.CancelledError
    return response


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
    admitted = False
    try:
        if not _admission.acquire(blocking=False):
            busy = ConversionBusy()
            raise HTTPException(status_code=busy.status_code, detail=busy.detail)
        admitted = True
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
        try:
            artifact = await run_conversion(data, fmt, currency, preview)
        except ConversionRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        return await _finish_response(
            artifact, data, account_id, fmt, currency,
            idempotency_key, metered, LEDGER,
        )
    finally:
        # Closing releases memory and deletes rejected or forced disk spills.
        # Shield the worker-thread close so cancellation cannot skip cleanup.
        try:
            with CancelScope(shield=True):
                await file.close()
        finally:
            if admitted:
                _admission.release()


def create_app() -> FastAPI:
    """Factory for ASGI servers (``uvicorn --factory statement_to_excel.api:create_app``)."""
    return app
