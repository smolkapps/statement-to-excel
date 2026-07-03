"""Generate synthetic bank-statement PDFs + exact expected JSON for tests.

No private data: every fixture is fabricated here with reportlab. Run this to
(re)create the committed fixtures:

    python tests/make_fixtures.py

It writes, under tests/fixtures/:
  * acmebank.pdf          ruled checking: Date|Description|Debit|Credit|Balance
  * columnarcredit.pdf    credit-card: Date|Description|Amount (parens negatives)
  * minimalchecking.pdf   borderless: "Mon DD  desc...  amount  balance"
  * scanned_empty.pdf     a page with NO extractable text (OCR-only) -> error path
plus <name>.expected.json with the ground-truth transactions for the first three.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle

FIX = Path(__file__).resolve().parent / "fixtures"
FIX.mkdir(parents=True, exist_ok=True)


def _dec(s: str) -> str:
    return f"{Decimal(s):f}"


# --------------------------------------------------------------------------- #
# 1) acmebank — clean ruled table, separate Debit/Credit columns
# --------------------------------------------------------------------------- #
def make_acmebank():
    rows = [
        ["Date", "Description", "Debit", "Credit", "Balance"],
        ["01/03/2024", "OPENING BALANCE", "", "", "2,000.00"],
        ["01/05/2024", "ACH PAYROLL DEPOSIT", "", "3,250.00", "5,250.00"],
        ["01/08/2024", "WHOLE FOODS MARKET #123", "84.21", "", "5,165.79"],
        ["01/12/2024", "RENT - OAK PROPERTY MGMT", "1,800.00", "", "3,365.79"],
        ["01/19/2024", "REFUND - AMAZON.COM", "", "29.99", "3,395.78"],
        ["01/27/2024", "CITY POWER & LIGHT", "142.55", "", "3,253.23"],
    ]
    c = canvas.Canvas(str(FIX / "acmebank.pdf"), pagesize=LETTER, invariant=1)
    w, h = LETTER
    c.setFont("Helvetica-Bold", 16)
    c.drawString(1 * inch, h - 1 * inch, "ACME BANK — Checking Statement")
    c.setFont("Helvetica", 10)
    c.drawString(1 * inch, h - 1.25 * inch, "Statement period: January 2024")
    tbl = Table(
        rows, colWidths=[1.0 * inch, 2.6 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch]
    )
    tbl.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ]
        )
    )
    tw, th = tbl.wrapOn(c, w, h)
    tbl.drawOn(c, 1 * inch, h - 1.5 * inch - th)
    c.showPage()
    c.save()

    expected = [
        {
            "date": "2024-01-05",
            "description": "ACH PAYROLL DEPOSIT",
            "amount": _dec("3250.00"),
            "balance": _dec("5250.00"),
            "currency": "USD",
            "type": "credit",
        },
        {
            "date": "2024-01-08",
            "description": "WHOLE FOODS MARKET #123",
            "amount": _dec("-84.21"),
            "balance": _dec("5165.79"),
            "currency": "USD",
            "type": "debit",
        },
        {
            "date": "2024-01-12",
            "description": "RENT - OAK PROPERTY MGMT",
            "amount": _dec("-1800.00"),
            "balance": _dec("3365.79"),
            "currency": "USD",
            "type": "debit",
        },
        {
            "date": "2024-01-19",
            "description": "REFUND - AMAZON.COM",
            "amount": _dec("29.99"),
            "balance": _dec("3395.78"),
            "currency": "USD",
            "type": "credit",
        },
        {
            "date": "2024-01-27",
            "description": "CITY POWER & LIGHT",
            "amount": _dec("-142.55"),
            "balance": _dec("3253.23"),
            "currency": "USD",
            "type": "debit",
        },
    ]
    (FIX / "acmebank.expected.json").write_text(json.dumps(expected, indent=2))


# --------------------------------------------------------------------------- #
# 2) columnarcredit — credit-card style, single Amount col w/ parens negatives
# --------------------------------------------------------------------------- #
def make_columnarcredit():
    rows = [
        ["Date", "Description", "Amount", "Balance"],
        ["2024-02-02", "Payment - Thank You", "(500.00)", "1,000.00"],
        ["2024-02-04", "BLUE BOTTLE COFFEE", "6.75", "1,006.75"],
        ["2024-02-09", "DELTA AIR LINES", "412.30", "1,419.05"],
        ["2024-02-15", "STATEMENT CREDIT", "(25.00)", "1,394.05"],
        ["2024-02-21", "APPLE.COM/BILL", "9.99", "1,404.04"],
    ]
    c = canvas.Canvas(str(FIX / "columnarcredit.pdf"), pagesize=LETTER, invariant=1)
    w, h = LETTER
    c.setFont("Helvetica-Bold", 16)
    c.drawString(1 * inch, h - 1 * inch, "Columnar Credit Card — February 2024")
    tbl = Table(rows, colWidths=[1.2 * inch, 2.8 * inch, 1.2 * inch, 1.2 * inch])
    tbl.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ]
        )
    )
    tw, th = tbl.wrapOn(c, w, h)
    tbl.drawOn(c, 1 * inch, h - 1.5 * inch - th)
    c.showPage()
    c.save()

    # Amount column: parentheses => negative (a payment/credit reduces the card
    # balance here). We keep the literal sign semantics of parse_amount.
    expected = [
        {
            "date": "2024-02-02",
            "description": "Payment - Thank You",
            "amount": _dec("-500.00"),
            "balance": _dec("1000.00"),
            "currency": "USD",
            "type": "debit",
        },
        {
            "date": "2024-02-04",
            "description": "BLUE BOTTLE COFFEE",
            "amount": _dec("6.75"),
            "balance": _dec("1006.75"),
            "currency": "USD",
            "type": "credit",
        },
        {
            "date": "2024-02-09",
            "description": "DELTA AIR LINES",
            "amount": _dec("412.30"),
            "balance": _dec("1419.05"),
            "currency": "USD",
            "type": "credit",
        },
        {
            "date": "2024-02-15",
            "description": "STATEMENT CREDIT",
            "amount": _dec("-25.00"),
            "balance": _dec("1394.05"),
            "currency": "USD",
            "type": "debit",
        },
        {
            "date": "2024-02-21",
            "description": "APPLE.COM/BILL",
            "amount": _dec("9.99"),
            "balance": _dec("1404.04"),
            "currency": "USD",
            "type": "credit",
        },
    ]
    (FIX / "columnarcredit.expected.json").write_text(json.dumps(expected, indent=2))


# --------------------------------------------------------------------------- #
# 3) minimalchecking — borderless text, "Mon DD" dates, year only in header
# --------------------------------------------------------------------------- #
def make_minimalchecking():
    c = canvas.Canvas(str(FIX / "minimalchecking.pdf"), pagesize=LETTER, invariant=1)
    w, h = LETTER
    c.setFont("Courier-Bold", 12)
    c.drawString(1 * inch, h - 1 * inch, "MINIMAL CREDIT UNION")
    c.setFont("Courier", 10)
    c.drawString(1 * inch, h - 1.2 * inch, "Account Statement  -  Year 2024")
    lines = [
        "Mar 01   OPENING BALANCE                          1500.00",
        "Mar 03   DIRECT DEPOSIT EMPLOYER INC      2100.00  3600.00",
        "Mar 07   GROCERY OUTLET                     58.40  3541.60",
        "         produce dept downtown",
        "Mar 14   ELECTRIC UTILITY AUTOPAY          120.00  3421.60",
        "Mar 22   ATM WITHDRAWAL                     200.00  3221.60",
        "Mar 29   INTEREST PAYMENT                    1.25  3222.85",
    ]
    y = h - 1.5 * inch
    for ln in lines:
        c.drawString(1 * inch, y, ln)
        y -= 0.22 * inch
    c.showPage()
    c.save()

    # NOTE: single trailing number on the opening line => treated as amount,
    # which is not a real transaction; expected starts at the first 2-number row.
    # Signs come from the running-balance movement (this borderless layout has no
    # explicit debit/credit column): a balance drop is a debit, a rise a credit.
    expected = [
        {
            "date": "2024-03-03",
            "description": "DIRECT DEPOSIT EMPLOYER INC",
            "amount": _dec("2100.00"),
            "balance": _dec("3600.00"),
            "currency": "USD",
            "type": "credit",
        },
        {
            "date": "2024-03-07",
            "description": "GROCERY OUTLET produce dept downtown",
            "amount": _dec("-58.40"),
            "balance": _dec("3541.60"),
            "currency": "USD",
            "type": "debit",
        },
        {
            "date": "2024-03-14",
            "description": "ELECTRIC UTILITY AUTOPAY",
            "amount": _dec("-120.00"),
            "balance": _dec("3421.60"),
            "currency": "USD",
            "type": "debit",
        },
        {
            "date": "2024-03-22",
            "description": "ATM WITHDRAWAL",
            "amount": _dec("-200.00"),
            "balance": _dec("3221.60"),
            "currency": "USD",
            "type": "debit",
        },
        {
            "date": "2024-03-29",
            "description": "INTEREST PAYMENT",
            "amount": _dec("1.25"),
            "balance": _dec("3222.85"),
            "currency": "USD",
            "type": "credit",
        },
    ]
    (FIX / "minimalchecking.expected.json").write_text(json.dumps(expected, indent=2))


# --------------------------------------------------------------------------- #
# 4) scanned_empty — a page with an image-ish block but NO text layer
# --------------------------------------------------------------------------- #
def make_scanned_empty():
    c = canvas.Canvas(str(FIX / "scanned_empty.pdf"), pagesize=LETTER, invariant=1)
    w, h = LETTER
    # Draw only vector rectangles — no text operators -> extract_text() == "".
    c.setFillColor(colors.lightgrey)
    c.rect(1 * inch, h - 4 * inch, 5 * inch, 2.5 * inch, fill=1, stroke=0)
    c.showPage()
    c.save()


def main():
    make_acmebank()
    make_columnarcredit()
    make_minimalchecking()
    make_scanned_empty()
    print(f"fixtures written to {FIX}")


if __name__ == "__main__":
    main()
