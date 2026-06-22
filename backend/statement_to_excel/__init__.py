"""statement-to-excel: convert bank-statement PDFs into clean spreadsheets.

This package exposes a small, well-tested engine that turns a *text-based*
bank-statement PDF into a list of normalized :class:`Transaction` objects and
writes them to ``.xlsx`` / ``.csv`` / ``.json``.

The public surface is intentionally tiny:

>>> from statement_to_excel import convert_pdf, to_xlsx_bytes
>>> txns = convert_pdf("statement.pdf")
>>> data = to_xlsx_bytes(txns)

Everything runs fully offline; there are no network calls or API keys in the
conversion path.
"""

from __future__ import annotations

from .transaction import Transaction
from .parsers import parse_amount, parse_date, looks_like_amount, looks_like_date
from .engine import (
    convert_text,
    convert_pdf,
    ConversionError,
    StatementSummary,
)
from .writers import (
    to_csv_bytes,
    to_json_bytes,
    to_xlsx_bytes,
    to_csv_str,
    to_json_str,
)

__all__ = [
    "Transaction",
    "parse_amount",
    "parse_date",
    "looks_like_amount",
    "looks_like_date",
    "convert_text",
    "convert_pdf",
    "ConversionError",
    "StatementSummary",
    "to_csv_bytes",
    "to_json_bytes",
    "to_xlsx_bytes",
    "to_csv_str",
    "to_json_str",
]

__version__ = "1.0.0"
