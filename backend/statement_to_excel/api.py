"""FastAPI application: upload a statement PDF, get back a spreadsheet.

Endpoints
---------
``GET  /api/health``                  liveness probe
``GET  /api/pricing``                 plan + credit-pack catalog (shared w/ UI)
``GET  /api/account/{id}``            metering state for an account
``POST /api/account/{id}/quote``      cost of processing N pages (no charge)
``POST /api/checkout``                start a (mock) purchase -> checkout url
``POST /api/checkout/{sid}/fulfill``  complete the (mock) purchase -> grant
``POST /api/convert``                 multipart PDF upload -> metered conversion

The conversion endpoint counts statement pages, *quotes* the charge, and only
spends credits/allowance after a successful parse. With the default mock billing
provider it needs no external services, so the test-suite drives the real ASGI
app end-to-end via Starlette's TestClient.
"""

from __future__ import annotations

import base64
import io

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from . import __version__
from .billing import InsufficientCredits, Ledger, PRICING, get_provider
from .engine import ConversionError, convert_pdf, summarize
from .writers import to_csv_bytes, to_xlsx_bytes

# A process-wide ledger + provider. In a real deploy these would be backed by a
# database and Stripe; here they are in-memory and deterministic.
LEDGER = Ledger()
PROVIDER = get_provider()

app = FastAPI(title="statement-to-excel", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class QuoteRequest(BaseModel):
    pages: int


class CheckoutRequest(BaseModel):
    account_id: str
    sku: str


def _account_view(account_id: str) -> dict:
    acct = LEDGER.get_or_create(account_id)
    return {
        "id": acct.id,
        "plan": acct.plan_id,
        "credits": acct.credits,
        "included_pages": acct.plan.included_pages,
        "pages_used_this_cycle": acct.pages_used_this_cycle,
        "included_remaining": acct.included_remaining(),
    }


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "billing": PROVIDER.name}


@app.get("/api/pricing")
def pricing() -> dict:
    return PRICING


@app.get("/api/account/{account_id}")
def get_account(account_id: str) -> dict:
    return _account_view(account_id)


@app.post("/api/account/{account_id}/quote")
def quote(account_id: str, body: QuoteRequest) -> dict:
    if body.pages < 0:
        raise HTTPException(status_code=400, detail="pages must be >= 0")
    acct = LEDGER.get_or_create(account_id)
    return acct.quote(body.pages)


@app.post("/api/checkout")
def checkout(body: CheckoutRequest) -> dict:
    try:
        return PROVIDER.create_checkout(body.account_id, body.sku)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/checkout/{session_id}/fulfill")
def fulfill(session_id: str) -> dict:
    try:
        acct = PROVIDER.fulfill(LEDGER, session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"fulfilled": True, "account": _account_view(acct.id)}


def _count_pages(data: bytes) -> int:
    """Count PDF pages cheaply via pdfplumber; default to 1 on failure."""
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return max(1, len(pdf.pages))
    except Exception:
        return 1


@app.post("/api/convert")
async def convert(
    file: UploadFile = File(...),
    account_id: str = Form("anon"),
    fmt: str = Form("xlsx"),
    currency: str = Form("USD"),
    preview: bool = Form(False),
) -> Response:
    """Metered conversion. With ``preview`` set (and a binary ``fmt``), the
    response is JSON carrying both the parsed rows *and* the file
    base64-inline, so a UI can show the preview table and offer the download
    from one call — charging the account once instead of twice."""
    fmt = (fmt or "xlsx").lower()
    if fmt not in {"xlsx", "csv", "json"}:
        raise HTTPException(status_code=400, detail="fmt must be xlsx|csv|json")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")

    pages = _count_pages(data)
    acct = LEDGER.get_or_create(account_id)
    if not acct.can_process(pages):
        q = acct.quote(pages)
        return JSONResponse(
            status_code=402,
            content={
                "error": "insufficient_credits",
                "detail": (
                    f"This {pages}-page statement needs "
                    f"{q['from_credits']} credit(s); you have {acct.credits}."
                ),
                "quote": q,
            },
        )

    # Parse first; only charge on success.
    try:
        txns = convert_pdf(io.BytesIO(data), currency=currency)
    except ConversionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        charge = LEDGER.charge_pages(account_id, pages)
    except InsufficientCredits as exc:  # pragma: no cover - guarded above
        raise HTTPException(status_code=402, detail=str(exc))

    summary = summarize(txns).to_dict()

    if fmt == "json":
        # Return JSON inline with metadata (handy for the UI table).
        return JSONResponse(
            content={
                "transactions": [t.to_dict() for t in txns],
                "summary": summary,
                "charge": charge,
            }
        )

    if fmt == "csv":
        body = to_csv_bytes(txns)
        media = "text/csv"
        ext = "csv"
    else:
        body = to_xlsx_bytes(txns)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ext = "xlsx"

    if preview:
        return JSONResponse(
            content={
                "transactions": [t.to_dict() for t in txns],
                "summary": summary,
                "charge": charge,
                "file_b64": base64.b64encode(body).decode("ascii"),
                "filename": f"statement.{ext}",
                "media_type": media,
            }
        )

    headers = {
        "Content-Disposition": f'attachment; filename="statement.{ext}"',
        "X-Transaction-Count": str(summary["count"]),
        "X-Credits-Remaining": str(charge["credits_after"]),
    }
    return Response(content=body, media_type=media, headers=headers)


def create_app() -> FastAPI:
    """Factory for ASGI servers (``uvicorn --factory statement_to_excel.api:create_app``)."""
    return app
