"""Deterministic, wholly invented US bank-inspired layout accuracy corpus.

These layouts exercise common statement conventions; they are not copies of,
or claims of compatibility with, current bank templates. Ground truth is made
before rendering, without importing any converter or parser. No customer data.

Run: python -m tests.accuracy_harness [--output DIR]
"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle


@dataclass(frozen=True)
class Layout:
    slug: str
    bank: str
    style: str
    pages: int = 1
    balances: bool = True
    reverse: bool = False


LAYOUTS = (
    Layout("chase", "Chase", "split"),
    Layout("bank-of-america", "Bank of America", "short-signed"),
    Layout("wells-fargo", "Wells Fargo", "month-delta", pages=2),
    Layout("citi", "Citi", "posted-date"),
    Layout("us-bank", "U.S. Bank", "iso-signed", pages=2),
    Layout("pnc", "PNC", "credit-first", pages=2),
    Layout("capital-one", "Capital One", "short-signed", balances=False),
    Layout("truist", "Truist", "wrapped-table"),
    Layout("td-bank", "TD Bank", "dr-cr"),
    Layout("bmo", "BMO", "month-delta", reverse=True),
)

# A deterministic fixed corpus: duplicate same-day transactions, penny amounts,
# a zero, thousands separators, mixed cash-flow signs, and numeric memo suffixes.
AMOUNTS = (
    "2400.00", "-84.21", "-1800.00", "29.99", "-0.01", "10.00",
    "-10.00", "-10.00", "1.25", "-142.55", "0.00", "300.50",
)
DESCRIPTIONS = (
    "SYNTHETIC PAYROLL", "SYNTHETIC GROCERY", "SYNTHETIC RENT",
    "SYNTHETIC REFUND", "SYNTHETIC ROUNDING", "SYNTHETIC TRANSFER IN",
    "SYNTHETIC DUPLICATE PURCHASE", "SYNTHETIC DUPLICATE PURCHASE",
    "SYNTHETIC INTEREST", "SYNTHETIC UTILITY", "SYNTHETIC ZERO ADJUSTMENT",
    "SYNTHETIC BATCH 42",
)


def ground_truth(layout: Layout) -> list[dict]:
    """Exact independent source data; never obtained from extraction output."""
    balance = Decimal("2000.00")
    rows = []
    for i, (amount_text, description) in enumerate(zip(AMOUNTS, DESCRIPTIONS)):
        amount = Decimal(amount_text)
        balance += amount
        # Two genuinely equal rows must both survive; a set-based metric fails.
        offset = 6 if i == 7 else i
        description += " downtown market" if i == 1 and layout.style in {"month-delta", "wrapped-table"} else ""
        rows.append({
            "date": (date(2024, 1, 2) + timedelta(days=offset)).isoformat(),
            "description": description,
            "amount": str(amount),
            "balance": str(balance) if layout.balances else None,
            "currency": "USD",
            "type": "debit" if amount < 0 else "credit",
        })
    return list(reversed(rows)) if layout.reverse else rows


def _money(text: str | None, *, absolute: bool = False) -> str:
    value = Decimal(text or "0")
    return f"{abs(value) if absolute else value:,.2f}"


def _header(c: canvas.Canvas, layout: Layout, page: int) -> None:
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, 750, f"{layout.bank} - SYNTHETIC TEST STATEMENT")
    c.setFont("Helvetica", 9)
    c.drawString(40, 733, "Statement period: January 1 - January 31, 2024")
    c.drawString(40, 719, "Account ending 0000 - fictional test account")
    c.drawString(40, 25, f"Page {page} of {layout.pages} - SYNTHETIC ONLY")


def render(layout: Layout, directory: Path) -> tuple[Path, list[dict]]:
    """Create a fresh synthetic PDF and its source-of-truth JSON sidecar."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{layout.slug}.pdf"
    expected = ground_truth(layout)
    c = canvas.Canvas(str(target), pagesize=LETTER, invariant=1)
    per_page = (len(expected) + layout.pages - 1) // layout.pages
    for page in range(layout.pages):
        _header(c, layout, page + 1)
        block = expected[page * per_page:(page + 1) * per_page]
        if layout.style in {"split", "posted-date", "credit-first", "wrapped-table"}:
            if layout.style == "posted-date":
                # Posting date, not purchase date, drives the statement ledger.
                header = ["Transaction Date", "Posted Date", "Description", "Amount", "Balance"]
                table_rows = [header] + [
                    [(date.fromisoformat(r["date"]) - timedelta(days=1)).strftime("%m/%d"),
                     date.fromisoformat(r["date"]).strftime("%m/%d"), r["description"],
                     _money(r["amount"]), _money(r["balance"])] for r in block
                ]
                widths = [72, 64, 226, 76, 76]
            else:
                credit_first = layout.style == "credit-first"
                header = ["Date", "Description", "Deposits" if credit_first else "Withdrawals",
                          "Withdrawals" if credit_first else "Deposits", "Balance"]
                table_rows = [header]
                for r in block:
                    amount = Decimal(r["amount"])
                    debit = _money(r["amount"], absolute=True) if amount < 0 else ""
                    credit = _money(r["amount"], absolute=True) if amount >= 0 else ""
                    desc = r["description"].replace(" downtown market", "\ndowntown market")
                    table_rows.append([date.fromisoformat(r["date"]).strftime("%m/%d/%Y"), desc,
                                       credit if credit_first else debit,
                                       debit if credit_first else credit, _money(r["balance"])])
                widths = [74, 226, 72, 72, 70]
            table = Table(table_rows, colWidths=widths)
            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), .5, colors.black),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
            ]))
            _, height = table.wrapOn(c, 514, 600)
            table.drawOn(c, 40, 696 - height)
        else:
            c.setFont("Courier", 8)
            y = 695
            if layout.style == "month-delta" and not layout.reverse and page == 0:
                c.drawString(40, y, "Jan 01 OPENING BALANCE 2,000.00")
                y -= 16
            c.drawString(40, y, "Date Description Amount" + (" Balance" if layout.balances else ""))
            y -= 18
            for r in block:
                fmt = {"short-signed": "%m/%d", "iso-signed": "%Y-%m-%d",
                       "month-delta": "%b %d", "dr-cr": "%m/%d/%Y"}[layout.style]
                dt = date.fromisoformat(r["date"]).strftime(fmt)
                desc = r["description"].replace(" downtown market", "")
                if layout.style == "month-delta":
                    amount = _money(r["amount"], absolute=True)
                elif layout.style == "dr-cr":
                    amount = "$ " + _money(r["amount"], absolute=True) + (" DR" if Decimal(r["amount"]) < 0 else " CR")
                else:
                    amount = _money(r["amount"])
                suffix = (" " + _money(r["balance"])) if layout.balances else ""
                c.drawString(40, y, f"{dt} {desc} {amount}{suffix}")
                y -= 16
                if " downtown market" in r["description"]:
                    c.drawString(40, y, "    downtown market")
                    y -= 16
            if layout.reverse and page == layout.pages - 1:
                c.drawString(40, y, "Jan 01 OPENING BALANCE 2,000.00")
        c.showPage()
    c.save()
    target.with_suffix(".expected.json").write_text(json.dumps(expected, indent=2) + "\n")
    return target, expected


def _row_key(row: dict) -> tuple:
    """Exact money, date, sign/type, description, balance, and currency match."""
    return (row["date"], row["description"], Decimal(row["amount"]),
            Decimal(row["balance"]) if row["balance"] is not None else None,
            row["currency"], row["type"])


def measure(expected: list[dict], actual: list[dict]) -> dict:
    """Ordered exact matches / max(row counts); extras and duplicates count.

    SequenceMatcher preserves multiplicity and order. A row with any incorrect
    field is wrong, rather than being partly credited for correct easy fields.
    """
    a = [_row_key(r) for r in expected]
    b = [_row_key(r) for r in actual]
    matched = sum(block.size for block in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
    denominator = max(len(a), len(b))
    return {"expected": len(a), "actual": len(b), "matched": matched,
            "accuracy": matched / denominator if denominator else 1.0}


def run(directory: Path) -> list[dict]:
    from statement_to_excel.engine import ConversionError, convert_pdf

    results = []
    for layout in LAYOUTS:
        path, expected = render(layout, directory)
        try:
            actual = [t.to_dict() for t in convert_pdf(path)]
            result = measure(expected, actual)
        except ConversionError as exc:
            result = measure(expected, [])
            result["error"] = str(exc)
        results.append({"bank": layout.bank, "layout": layout.style, **result})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Keep generated synthetic PDFs, truth and report here")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="stx-accuracy-") as temporary:
        directory = args.output or Path(temporary)
        results = run(directory)
        print("| Bank (synthetic inspired layout) | Expected | Extracted | Exact ordered rows | Accuracy |")
        print("| --- | ---: | ---: | ---: | ---: |")
        for r in results:
            print(f"| {r['bank']} | {r['expected']} | {r['actual']} | {r['matched']} | {r['accuracy']:.1%} |")
            if r.get("error"):
                print(f"  {r['error']}")
        if args.output:
            (directory / "accuracy-report.json").write_text(json.dumps(results, indent=2) + "\n")
        print("Gate: 100% exact ordered rows for every synthetic layout. This is regression coverage, not a real-bank accuracy estimate.")
        return 0 if all(r["accuracy"] == 1 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
