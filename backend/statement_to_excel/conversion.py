"""In-memory document preparation, with no HTTP or billing side effects."""

from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass

from .engine import ConversionError, convert_pdf, summarize
from .writers import to_csv_bytes, to_xlsx_bytes

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_STATEMENT_PAGES = 100
MAX_OUTPUT_BYTES = 64 * 1024 * 1024


class ConversionRejected(Exception):
    """A safe public error; arbitrary parser/worker exceptions never cross IPC."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class ConversionArtifact:
    pages: int
    transaction_count: int
    body: bytes
    media_type: str


def count_pages(data: bytes) -> int:
    """Stop reading page metadata at the first page beyond the supported cap."""
    try:
        from pdfminer.pdfpage import PDFPage
        with io.BytesIO(data) as stream:
            pages = sum(1 for _ in PDFPage.get_pages(stream, maxpages=MAX_STATEMENT_PAGES + 1))
        return max(1, pages)
    except Exception:
        # The converter supplies the existing actionable password/format errors.
        return 1


def prepare_conversion(data: bytes, fmt: str, currency: str, preview: bool) -> ConversionArtifact:
    """Finish every document-dependent operation before the parent may debit usage."""
    pages = count_pages(data)
    if pages > MAX_STATEMENT_PAGES:
        raise ConversionRejected(413, "PDF statements are limited to 100 pages")
    try:
        txns = convert_pdf(io.BytesIO(data), currency=currency)
    except ConversionError as exc:
        raise ConversionRejected(422, str(exc)) from exc

    summary = summarize(txns).to_dict()
    media_type = "application/json"
    if fmt == "csv":
        body = to_csv_bytes(txns)
        media_type = "text/csv"
    elif fmt == "xlsx":
        body = to_xlsx_bytes(txns)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        body = b""
    if fmt == "json" or preview:
        result = {
            "transactions": [t.to_dict() for t in txns],
            "summary": summary,
            "reconciliation": txns.reconciliation.to_dict(),
            "layout": txns.layout,
        }
        if fmt != "json":
            result.update(file_b64=base64.b64encode(body).decode("ascii"),
                          filename=f"statement.{fmt}", media_type=media_type)
        # No transaction serialization or base64 work remains after billing.
        body = json.dumps(result, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")
        media_type = "application/json"
    if len(body) > MAX_OUTPUT_BYTES:
        raise ConversionRejected(422, "Conversion output is too large. Split the statement into fewer pages and try again.")
    return ConversionArtifact(pages, len(txns), body, media_type)
