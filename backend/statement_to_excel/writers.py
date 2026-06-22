"""Serialize a list of :class:`Transaction` to CSV / JSON / XLSX.

XLSX is the headline format (it's "statement *to excel*"): the workbook gets a
formatted ``Transactions`` sheet with real numeric/date cells plus a
``Summary`` sheet with debit/credit/net totals.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from decimal import Decimal
from typing import Sequence

from .transaction import Transaction

__all__ = [
    "to_csv_bytes",
    "to_json_bytes",
    "to_xlsx_bytes",
    "to_csv_str",
    "to_json_str",
]

_COLUMNS = ["date", "description", "amount", "balance", "currency", "type"]


def to_csv_str(txns: Sequence[Transaction]) -> str:
    """Return a CSV string with a header row and exact decimal amounts."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(_COLUMNS)
    for t in txns:
        d = t.to_dict()
        writer.writerow([d[c] if d[c] is not None else "" for c in _COLUMNS])
    return buf.getvalue()


def to_csv_bytes(txns: Sequence[Transaction]) -> bytes:
    return to_csv_str(txns).encode("utf-8")


def to_json_str(txns: Sequence[Transaction]) -> str:
    """Return pretty JSON: ``{"transactions": [...]}`` with stringified Decimals."""
    return json.dumps(
        {"transactions": [t.to_dict() for t in txns]}, indent=2, ensure_ascii=False
    )


def to_json_bytes(txns: Sequence[Transaction]) -> bytes:
    return to_json_str(txns).encode("utf-8")


def _to_float(value):
    # openpyxl wants native numbers for numeric cells; Decimal -> float is safe
    # for display (we keep exact values in CSV/JSON). Guard against None.
    if value is None:
        return None
    return float(value) if isinstance(value, Decimal) else value


def to_xlsx_bytes(txns: Sequence[Transaction]) -> bytes:
    """Build a styled .xlsx workbook in memory and return its bytes.

    Requires the ``openpyxl`` dependency (a hard dependency of this package).
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Transactions"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F2937")
    money_fmt = "#,##0.00;[Red](#,##0.00)"

    ws.append([c.capitalize() for c in _COLUMNS])
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for t in txns:
        iso = t.date
        try:
            y, m, d = (int(x) for x in iso.split("-"))
            date_cell = date(y, m, d)
        except Exception:
            date_cell = iso
        ws.append(
            [
                date_cell,
                t.description,
                _to_float(t.amount),
                _to_float(t.balance),
                t.currency,
                t.type,
            ]
        )

    # Number formats on amount + balance columns; date format on the date column.
    for row in ws.iter_rows(min_row=2):
        row[0].number_format = "yyyy-mm-dd"
        row[2].number_format = money_fmt
        if row[3].value is not None:
            row[3].number_format = money_fmt

    # Column widths.
    widths = {1: 12, 2: 48, 3: 14, 4: 14, 5: 10, 6: 8}
    for idx, w in widths.items():
        ws.column_dimensions[get_column_letter(idx)].width = w
    ws.freeze_panes = "A2"

    # Summary sheet.
    from .engine import summarize

    s = summarize(txns)
    ws2 = wb.create_sheet("Summary")
    rows = [
        ("Metric", "Value"),
        ("Transactions", s.count),
        ("Total debit", _to_float(s.total_debit)),
        ("Total credit", _to_float(s.total_credit)),
        ("Net", _to_float(s.net)),
        ("Currency", s.currency),
        ("Start date", s.start_date or ""),
        ("End date", s.end_date or ""),
    ]
    for r in rows:
        ws2.append(list(r))
    for cell in ws2[1]:
        cell.font = header_font
        cell.fill = header_fill
    for i in (3, 4, 5):
        ws2.cell(row=i, column=2).number_format = money_fmt
    ws2.column_dimensions["A"].width = 16
    ws2.column_dimensions["B"].width = 18

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
