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
    account_type: str = "deposit"
    family: str = ""
    variation: str = ""


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

# Keep the original public list and fixture filenames stable for browser tests
# and consumers. Additional card families and adversarial cases join the corpus
# explicitly, rather than replacing any of the original ten deposit layouts.
CARD_LAYOUTS = (
    Layout("chase-card", "Chase credit card", "card-sections", account_type="card"),
    Layout("citi-card", "Citi credit card", "card-minus", account_type="card"),
    Layout("capital-one-card", "Capital One credit card", "card-lines", account_type="card"),
    Layout("american-express-card", "American Express credit card", "card-iso", account_type="card"),
)
VARIATION_LAYOUTS = (
    Layout("chase-card-year-boundary", "Chase credit card", "card-sections", account_type="card",
           family="chase-card", variation="year-boundary"),
    Layout("chase-card-year-boundary-end-year", "Chase credit card", "card-sections", account_type="card",
           family="chase-card", variation="year-boundary-end-year"),
    Layout("citi-card-multiline", "Citi credit card", "card-minus", account_type="card",
           family="citi-card", variation="multiline"),
    Layout("citi-page-break", "Citi", "posted-date", pages=3,
           family="citi", variation="page-break"),
    Layout("american-express-card-no-activity", "American Express credit card", "card-iso",
           account_type="card", family="american-express-card", variation="no-activity"),
    Layout("wells-fargo-overdraft", "Wells Fargo", "month-delta", pages=2,
           family="wells-fargo", variation="overdraft"),
    Layout("chase-million", "Chase", "split", family="chase", variation="million"),
    Layout("capital-one-card-40-pages", "Capital One credit card", "card-sections", pages=40,
           account_type="card", family="capital-one-card", variation="40-pages"),
)
CORPUS_LAYOUTS = LAYOUTS + CARD_LAYOUTS + VARIATION_LAYOUTS

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
    if layout.account_type == "card":
        return _card_ground_truth(layout)
    balance = _opening(layout)
    rows = []
    for i, (amount_text, description) in enumerate(zip(AMOUNTS, DESCRIPTIONS)):
        amount = Decimal(amount_text) * (1000 if layout.variation == "million" else 1)
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


def _opening(layout: Layout) -> Decimal:
    return Decimal("-4000.00" if layout.variation == "overdraft" else
                   "2000000.00" if layout.variation == "million" else "2000.00")


def _card_ground_truth(layout: Layout) -> list[dict]:
    if layout.variation == "no-activity":
        return []
    source = [
        ("1200.00", "SYNTHETIC ONLINE PAYMENT", "payment_credit"),
        ("25.00", "SYNTHETIC REFUND CREDIT", "payment_credit"),
        ("-84.21", "SYNTHETIC GROCERY", "purchase"),
        ("-1800.00", "SYNTHETIC EQUIPMENT", "purchase"),
        ("-29.99", "SYNTHETIC SUBSCRIPTION", "purchase"),
        ("-0.01", "SYNTHETIC ROUNDING PURCHASE", "purchase"),
        ("-15.00", "SYNTHETIC LATE FEE", "fee"),
        ("-12.34", "SYNTHETIC INTEREST CHARGE", "interest"),
    ]
    if layout.variation == "40-pages":
        # Real transactions appear on every one of the forty pages; this is not
        # a short table padded with blank pages. Sections cross page boundaries.
        source = [("10.00", f"SYNTHETIC ONLINE PAYMENT {i:03}", "payment_credit") for i in range(8)]
        source += [("-2.50", f"SYNTHETIC PURCHASE {i:03}", "purchase") for i in range(144)]
        source += [("-1.00", f"SYNTHETIC SERVICE FEE {i:03}", "fee") for i in range(4)]
        source += [("-0.25", f"SYNTHETIC INTEREST CHARGE {i:03}", "interest") for i in range(4)]
    start = date(2023, 12, 28) if layout.variation.startswith("year-boundary") else date(2024, 1, 2)
    balance = _opening(layout)
    rows = []
    for i, (text, description, category) in enumerate(source):
        amount = Decimal(text)
        balance -= amount  # Card running balances are debt, opposite cash flow.
        if layout.variation == "multiline" and category == "purchase" and i == 2:
            description += " downtown market"
        offset = i // 6 if layout.variation == "40-pages" else i
        rows.append({"date": (start + timedelta(days=offset)).isoformat(),
                     "description": description, "amount": str(amount),
                     "balance": str(balance), "currency": "USD",
                     "type": "debit" if amount < 0 else "credit", "category": category})
    return rows


def _money(text: str | None, *, absolute: bool = False) -> str:
    value = Decimal(text or "0")
    return f"{abs(value) if absolute else value:,.2f}"


def _header(c: canvas.Canvas, layout: Layout, page: int) -> None:
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, 750, f"{layout.bank} - SYNTHETIC TEST STATEMENT")
    c.setFont("Helvetica", 9)
    period = ("December 20 - January 19, 2024" if layout.variation == "year-boundary-end-year" else
              "December 20, 2023 - January 19, 2024" if layout.variation == "year-boundary"
              else "January 1 - January 31, 2024")
    c.drawString(40, 733, f"Statement period: {period}")
    c.drawString(40, 719, "Account ending 0000 - fictional test account")
    c.drawString(40, 25, f"Page {page} of {layout.pages} - SYNTHETIC ONLY")


def printed_totals(layout: Layout, rows: list[dict]) -> dict[str, Decimal]:
    """Totals rendered from independent source data, never parser output."""
    opening = _opening(layout)
    if layout.account_type == "card":
        terms = {"previous_balance": opening}
        for category, key in (("payment_credit", "payments_credits"), ("purchase", "purchases"),
                              ("fee", "fees"), ("interest", "interest")):
            terms[key] = sum((abs(Decimal(r["amount"])) for r in rows if r["category"] == category), Decimal("0"))
        terms["new_balance"] = opening - terms["payments_credits"] + terms["purchases"] + terms["fees"] + terms["interest"]
        return terms
    money_in = sum((Decimal(r["amount"]) for r in rows if Decimal(r["amount"]) >= 0), Decimal("0"))
    money_out = sum((-Decimal(r["amount"]) for r in rows if Decimal(r["amount"]) < 0), Decimal("0"))
    return {"opening_balance": opening, "money_in": money_in, "money_out": money_out,
            "closing_balance": opening + money_in - money_out}


def _summary(c: canvas.Canvas, layout: Layout, rows: list[dict]) -> None:
    totals = printed_totals(layout, rows)
    labels = (("Previous Balance", "previous_balance"), ("Payments and Credits", "payments_credits"),
              ("Purchases", "purchases"), ("Fees Charged", "fees"), ("Interest Charged", "interest"),
              ("New Balance", "new_balance")) if layout.account_type == "card" else (
                  ("Opening balance", "opening_balance"), ("Money in", "money_in"),
                  ("Money out", "money_out"), ("Closing balance", "closing_balance"))
    c.setFont("Helvetica", 9)
    for i, (label, key) in enumerate(labels):
        c.drawString(40, 700 - i * 13, f"{label}: {_money(str(totals[key]))}")


def _draw_table(c: canvas.Canvas, rows: list[list[str]], widths: list[int], top: int) -> int:
    table = Table(rows, colWidths=widths)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), .5, colors.black),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
    ]))
    _, height = table.wrapOn(c, 514, 600)
    table.drawOn(c, 40, top - height)
    return int(top - height)


def _render_card(c: canvas.Canvas, layout: Layout, block: list[dict], top: int) -> None:
    sections = (("payment_credit", "Payments and Credits"), ("purchase", "Purchases"),
                ("fee", "Fees"), ("interest", "Interest"))
    if not block:
        c.setFont("Helvetica", 10)
        c.drawString(40, top, "No activity. No transactions this statement period.")
        return
    for category, label in sections:
        section = [r for r in block if r["category"] == category]
        if not section:
            continue
        c.setFont("Helvetica-Bold", 10)
        c.drawString(40, top, label)
        if layout.style == "card-lines":
            c.setFont("Courier", 8)
            top -= 16
            c.drawString(40, top, "Transaction Date Posting Date Description Amount Balance")
            top -= 18
            for row in section:
                transaction_date = (date.fromisoformat(row["date"]) - timedelta(days=1)).strftime("%m/%d")
                posting_date = date.fromisoformat(row["date"]).strftime("%m/%d")
                c.drawString(40, top, f"{transaction_date} {posting_date} {row['description']} "
                             f"{_money(row['amount'], absolute=True)} {_money(row['balance'])}")
                top -= 16
            top -= 16
            continue
        table_rows = [["Transaction Date", "Posting Date", "Description", "Amount", "Balance"]]
        for row in section:
            native_amount = -Decimal(row["amount"])
            if layout.style == "card-sections":
                native_amount = abs(native_amount)  # Payments are in their own section.
            date_format = "%Y-%m-%d" if layout.style == "card-iso" else "%m/%d"
            table_rows.append([(date.fromisoformat(row["date"]) - timedelta(days=1)).strftime(date_format),
                               date.fromisoformat(row["date"]).strftime(date_format),
                               row["description"].replace(" downtown market", "\ndowntown market"),
                               _money(str(native_amount)), _money(row["balance"])])
        widths = [80, 80, 210, 72, 72] if layout.style == "card-iso" else [72, 64, 226, 76, 76]
        top = _draw_table(c, table_rows, widths, top - 8) - 20


def render(layout: Layout, directory: Path) -> tuple[Path, list[dict]]:
    """Create a fresh synthetic PDF and its source-of-truth JSON sidecar."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{layout.slug}.pdf"
    expected = ground_truth(layout)
    c = canvas.Canvas(str(target), pagesize=LETTER, invariant=1)
    per_page = (len(expected) + layout.pages - 1) // layout.pages
    for page in range(layout.pages):
        _header(c, layout, page + 1)
        if page == 0:
            _summary(c, layout, expected)
        top = 600 if page == 0 else 696
        block = expected[page * per_page:(page + 1) * per_page]
        if layout.account_type == "card":
            _render_card(c, layout, block, top)
        elif layout.style in {"split", "posted-date", "credit-first", "wrapped-table"}:
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
            _draw_table(c, table_rows, widths, top)
        else:
            c.setFont("Courier", 8)
            y = top
            if layout.style == "month-delta" and not layout.reverse and page == 0:
                c.drawString(40, y, f"Jan 01 OPENING BALANCE {_money(str(_opening(layout)))}")
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
                c.drawString(40, y, f"Jan 01 OPENING BALANCE {_money(str(_opening(layout)))}")
        c.showPage()
    c.save()
    target.with_suffix(".expected.json").write_text(json.dumps(expected, indent=2) + "\n")
    return target, expected


def _row_key(row: dict) -> tuple:
    """Exact money, date, sign/type, description, balance, and currency match."""
    return (row["date"], row["description"], Decimal(row["amount"]),
            Decimal(row["balance"]) if row["balance"] is not None else None,
            row["currency"], row["type"])


def measure(expected: list[dict], actual: list[dict], *, reconciliation_status: str | None = None) -> dict:
    """Ordered exact matches / max(row counts); extras and duplicates count.

    SequenceMatcher preserves multiplicity and order. A row with any incorrect
    field is wrong, rather than being partly credited for correct easy fields.
    """
    a = [_row_key(r) for r in expected]
    b = [_row_key(r) for r in actual]
    matched = sum(block.size for block in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
    denominator = max(len(a), len(b))
    accuracy = matched / denominator if denominator else 1.0
    return {"expected": len(a), "actual": len(b), "matched": matched,
            "missing": len(a) - matched, "extra": len(b) - matched,
            "accuracy": accuracy, "status": reconciliation_status,
            "silent_errors": int(reconciliation_status == "balanced" and accuracy != 1),
            "false_alarms": int(reconciliation_status == "not_balanced" and accuracy == 1)}


def run(directory: Path) -> list[dict]:
    from statement_to_excel.engine import ConversionError, convert_pdf

    results = []
    for layout in CORPUS_LAYOUTS:
        path, expected = render(layout, directory)
        try:
            transactions = convert_pdf(path)
            actual = [t.to_dict() for t in transactions]
            result = measure(expected, actual, reconciliation_status=transactions.reconciliation.status)
        except ConversionError as exc:
            result = measure(expected, [])
            result["error"] = str(exc)
        results.append({"bank": layout.bank, "family": layout.family or layout.slug,
                        "fixture": layout.slug, "layout": layout.style,
                        "variation": layout.variation or "standard", **result})
    return results


def per_family(results: list[dict]) -> list[dict]:
    """Aggregate fixture metrics without hiding a failure behind rounded rates."""
    families: dict[str, dict] = {}
    for result in results:
        family = families.setdefault(result["family"], {
            "family": result["family"], "bank": result["bank"], "statements": 0,
            "balanced": 0, "expected": 0, "actual": 0, "matched": 0,
            "missing": 0, "extra": 0, "silent_errors": 0, "false_alarms": 0,
            "correct_statements": 0,
        })
        family["statements"] += 1
        family["balanced"] += int(result["status"] == "balanced")
        family["correct_statements"] += int(result["accuracy"] == 1)
        for key in ("expected", "actual", "matched", "missing", "extra", "silent_errors", "false_alarms"):
            family[key] += result[key]
    for family in families.values():
        denominator = max(family["expected"], family["actual"])
        family["accuracy"] = family["matched"] / denominator if denominator else 1.0
        family["balance_rate"] = family["balanced"] / family["statements"]
    return list(families.values())


def report_table(families: list[dict]) -> str:
    lines = [
        "| Family (synthetic inspired layout) | Statements | Balance rate | Expected | Extracted | Exact ordered rows | Accuracy | Missing | Extra | Silent errors | False alarms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in families:
        lines.append(f"| {result['bank']} | {result['statements']} | {result['balance_rate']:.1%} | "
                     f"{result['expected']} | {result['actual']} | {result['matched']} | {result['accuracy']:.1%} | "
                     f"{result['missing']} | {result['extra']} | {result['silent_errors']} | {result['false_alarms']} |")
    return "\n".join(lines)


def passes_gates(results: list[dict]) -> bool:
    # Every fixture prints complete totals. Requiring balanced catches extraction
    # that would otherwise turn a regression into a superficially safe unknown.
    return all(result["accuracy"] == 1 and result["status"] == "balanced"
               and result["silent_errors"] == 0 and result["false_alarms"] == 0 for result in results)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Keep generated synthetic PDFs, truth and report here")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="stx-accuracy-") as temporary:
        directory = args.output or Path(temporary)
        results = run(directory)
        families = per_family(results)
        table = report_table(families)
        print(table)
        for r in results:
            if r.get("error"):
                print(f"  {r['fixture']}: {r['error']}")
        if args.output:
            # Preserve the original report's JSON list and row metric names.
            (directory / "accuracy-report.json").write_text(json.dumps(results, indent=2) + "\n")
            (directory / "accuracy-family-report.json").write_text(json.dumps(families, indent=2) + "\n")
            (directory / "accuracy-report.md").write_text(table + "\n")
        print(f"Silent errors: {sum(r['silent_errors'] for r in results)}; false alarms: {sum(r['false_alarms'] for r in results)}.")
        print("Gate: 100% exact ordered rows and balanced for every synthetic fixture; 0 silent errors and 0 false alarms. This is regression coverage, not a real-bank accuracy estimate.")
        return 0 if passes_gates(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
