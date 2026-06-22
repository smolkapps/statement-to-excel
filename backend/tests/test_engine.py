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
