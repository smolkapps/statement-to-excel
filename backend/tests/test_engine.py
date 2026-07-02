"""Engine tests against the synthetic PDF fixtures + error paths.

`acmebank` (clean ruled table) is asserted EXACTLY. The two messier layouts are
asserted on the fields that matter (date, amount, balance) with a field-level
accuracy floor, since description merging on borderless text is heuristic.
"""

from decimal import Decimal

import pytest

from statement_to_excel.engine import (
    ConversionError,
    convert_pdf,
    convert_text,
    summarize,
)
from tests.conftest import load_expected


def _key(t):
    return (t.date, t.amount, t.balance)


def test_acmebank_exact(fixtures_dir):
    txns = convert_pdf(fixtures_dir / "acmebank.pdf")
    expected = load_expected("acmebank")
    got = [t.to_dict() for t in txns]
    assert got == expected


def test_columnarcredit_exact(fixtures_dir):
    txns = convert_pdf(fixtures_dir / "columnarcredit.pdf")
    expected = load_expected("columnarcredit")
    got = [t.to_dict() for t in txns]
    assert got == expected


def test_minimalchecking_field_accuracy(fixtures_dir):
    txns = convert_pdf(fixtures_dir / "minimalchecking.pdf")
    expected = [
        (e["date"], Decimal(e["amount"]), Decimal(e["balance"]))
        for e in load_expected("minimalchecking")
    ]
    got = {_key(t) for t in txns}
    matched = sum(1 for e in expected if e in got)
    assert matched / len(expected) >= 0.85, (matched, len(expected), got)
    # description continuation should be folded for the GROCERY OUTLET row
    grocery = [t for t in txns if t.date == "2024-03-07"]
    assert grocery and "produce dept" in grocery[0].description


def test_minimalchecking_balance_delta_signs(fixtures_dir):
    """Borderless rows (no debit/credit column) get their sign from the running
    balance: a drop is a debit, a rise a credit — even though the amount token
    is written unsigned. Regression guard for the naive "everything is a credit"
    bug."""
    txns = convert_pdf(fixtures_dir / "minimalchecking.pdf")
    by_date = {t.date: t for t in txns}

    # GROCERY OUTLET drops 3600.00 -> 3541.60, so it must be a debit.
    grocery = by_date["2024-03-07"]
    assert grocery.amount == Decimal("-58.40")
    assert grocery.type == "debit"
    # ATM WITHDRAWAL and the utility autopay likewise decrease the balance.
    assert by_date["2024-03-14"].type == "debit"
    assert by_date["2024-03-22"].amount == Decimal("-200.00")
    # DIRECT DEPOSIT and INTEREST raise the balance -> credits.
    assert by_date["2024-03-03"].type == "credit"
    assert by_date["2024-03-03"].amount == Decimal("2100.00")
    assert by_date["2024-03-29"].type == "credit"

    # The dated single-number "OPENING BALANCE" line seeds the running balance
    # rather than becoming a phantom +1500 credit, so the FULL unfiltered
    # summarize() totals reconcile with the real cashflow — no date whitelist.
    assert "2024-03-01" not in by_date
    assert len(txns) == 5
    s = summarize(txns)
    assert s.total_credit == Decimal("2101.25")  # 2100.00 + 1.25
    assert s.total_debit == Decimal("378.40")  # 58.40 + 120.00 + 200.00
    assert s.net == Decimal("1722.85")


def test_balance_delta_infers_debit_on_borderless_line():
    """A single balance-decreasing borderless row is typed a debit, not the
    naive credit the unsigned amount token would otherwise produce."""
    txns = convert_text(
        lines=[
            "01/05/2024 OPENING DEPOSIT 500.00 500.00",
            "01/09/2024 HARDWARE STORE 30.00 470.00",
        ],
    )
    hardware = next(t for t in txns if t.date == "2024-01-09")
    assert hardware.amount == Decimal("-30.00")
    assert hardware.type == "debit"
    s = summarize(txns)
    assert s.total_debit == Decimal("30.00")
    assert s.total_credit == Decimal("500.00")
    assert s.net == Decimal("470.00")


def test_stale_balance_chain_keeps_explicit_sign():
    """A balance-less row leaves prev_balance stale, so the next row's delta
    spans two transactions and no longer matches that row's amount. The
    magnitude guard then declines to re-sign and the explicitly-parsed sign
    (parentheses => debit) survives instead of being flipped by the bogus
    delta direction."""
    txns = convert_text(
        lines=[
            "01/05/2024 OPENING DEPOSIT 500.00 500.00",
            "01/07/2024 MOBILE REFUND 20.00",  # no balance -> prev_balance stays 500
            "01/09/2024 CARD PURCHASE (5.00) 515.00",  # explicit debit
        ],
    )
    purchase = next(t for t in txns if t.date == "2024-01-09")
    # delta = 515 - 500 = +15 (spans the balance-less refund), which does NOT
    # match |amount| = 5, so the naive override that would flip this to +5.00
    # credit is declined and the parsed -5.00 debit is kept.
    assert purchase.amount == Decimal("-5.00")
    assert purchase.type == "debit"


def test_newest_first_statement_declines_to_resign():
    """On a reverse-chronological (newest-first) statement the delta between
    adjacent rows reflects a *neighbouring* row's amount, not the current one,
    so it won't match this row's magnitude. The guard declines rather than
    flipping a deposit into a bogus debit."""
    txns = convert_text(
        lines=[
            "03/10/2024 SECOND DEPOSIT 50.00 1050.00",
            "03/05/2024 FIRST DEPOSIT 900.00 1000.00",
        ],
    )
    first = next(t for t in txns if t.date == "2024-03-05")
    # delta = 1000 - 1050 = -50 would naively flip this to -900.00 debit; but
    # |delta| = 50 != |amount| = 900, so the parsed +900.00 credit is kept.
    assert first.amount == Decimal("900.00")
    assert first.type == "credit"


def test_scanned_pdf_raises(fixtures_dir):
    with pytest.raises(ConversionError):
        convert_pdf(fixtures_dir / "scanned_empty.pdf")


def test_convert_text_empty_raises():
    with pytest.raises(ConversionError):
        convert_text(full_text="nothing here", lines=["just words"], tables=[])


def test_summarize():
    txns = convert_text(
        lines=[
            "01/05/2024 PAYDAY 1000.00 1000.00",
            "01/06/2024 COFFEE -4.50 995.50",
        ],
    )
    s = summarize(txns)
    assert s.count == 2
    assert s.total_credit == Decimal("1000.00")
    assert s.total_debit == Decimal("4.50")
    assert s.net == Decimal("995.50")
    assert s.start_date == "2024-01-05"
    assert s.end_date == "2024-01-06"


def test_dayfirst_inference_from_unambiguous_date():
    # 25/12/2024 forces day-first; the other rows then parse day-first too.
    txns = convert_text(
        lines=[
            "25/12/2024 GIFT SHOP 50.00 450.00",
            "02/01/2024 NEW YEAR 10.00 440.00",
        ],
    )
    dates = sorted(t.date for t in txns)
    assert dates == ["2024-01-02", "2024-12-25"]


def test_table_strategy_beats_lines_when_both_present():
    # A ruled table with 3 rows should win over a single stray line.
    tables = [
        [
            ["Date", "Description", "Amount", "Balance"],
            ["01/01/2024", "A", "10.00", "10.00"],
            ["01/02/2024", "B", "-5.00", "5.00"],
            ["01/03/2024", "C", "20.00", "25.00"],
        ]
    ]
    lines = ["01/09/2024 STRAY 1.00 1.00"]
    txns = convert_text(tables=tables, lines=lines, full_text="2024")
    assert len(txns) == 3
    assert txns[0].description == "A"
