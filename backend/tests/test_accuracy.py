"""Strict end-to-end PDF accuracy gates and metric correctness."""

from copy import deepcopy

import pytest

from statement_to_excel.engine import convert_pdf
from tests.accuracy_harness import (
    CARD_LAYOUTS, CORPUS_LAYOUTS, LAYOUTS, VARIATION_LAYOUTS, ground_truth,
    measure, passes_gates, per_family, printed_totals, render, report_table,
)


@pytest.mark.parametrize("layout", CORPUS_LAYOUTS, ids=lambda layout: layout.slug)
def test_bank_inspired_pdf_exact_rows(layout, tmp_path):
    path, expected = render(layout, tmp_path)
    transactions = convert_pdf(path)
    actual = [transaction.to_dict() for transaction in transactions]
    result = measure(expected, actual, reconciliation_status=transactions.reconciliation.status)
    assert result["accuracy"] == 1.0, (layout.bank, result, actual, expected)
    assert result["status"] == "balanced", (layout.slug, transactions.reconciliation.to_dict())
    assert result["silent_errors"] == result["false_alarms"] == 0


@pytest.mark.parametrize("mutation", ["extra", "missing", "reorder", "sign", "description", "date", "balance", "currency", "type"])
def test_metric_penalizes_every_row_error(mutation):
    expected = ground_truth(LAYOUTS[6])  # no balances: rows 6/7 are truly identical
    actual = deepcopy(expected)
    if mutation == "extra":
        actual.append(deepcopy(actual[0]))
    elif mutation == "missing":
        actual.pop(7)  # lose an identical transaction, invisible to set metrics
    elif mutation == "reorder":
        actual[0], actual[1] = actual[1], actual[0]
    else:
        replacements = {"sign": ("amount", "-2400.00"), "description": ("description", "wrong"),
                        "date": ("date", "2024-01-31"), "balance": ("balance", "0.00"),
                        "currency": ("currency", "EUR"), "type": ("type", "debit")}
        field, value = replacements[mutation]
        actual[0][field] = value
    result = measure(expected, actual, reconciliation_status="balanced")
    assert result["accuracy"] < 1
    assert result["silent_errors"] == 1
    assert result["false_alarms"] == 0
    assert result["missing"] > 0 or result["extra"] > 0


def test_accuracy_generation_reproducible(tmp_path):
    for layout in CORPUS_LAYOUTS:
        path, expected = render(layout, tmp_path)
        first = path.read_bytes()
        path, again = render(layout, tmp_path)
        assert path.read_bytes() == first
        assert expected == again


@pytest.mark.parametrize("status,silent,false_alarm,passes", [
    ("balanced", 0, 0, True), ("not_balanced", 0, 1, False), ("cannot_check", 0, 0, False),
])
def test_correct_statement_status_gates(status, silent, false_alarm, passes):
    expected = ground_truth(LAYOUTS[0])
    result = measure(expected, expected, reconciliation_status=status)
    assert result["silent_errors"] == silent
    assert result["false_alarms"] == false_alarm
    assert passes_gates([result]) is passes


def test_missing_or_extra_duplicate_counts_are_not_hidden():
    expected = ground_truth(LAYOUTS[6])
    missing = measure(expected, expected[:7] + expected[8:], reconciliation_status="balanced")
    extra = measure(expected, expected + [expected[7]], reconciliation_status="balanced")
    assert (missing["missing"], missing["extra"]) == (1, 0)
    assert (extra["missing"], extra["extra"]) == (0, 1)
    assert missing["silent_errors"] == extra["silent_errors"] == 1


def test_empty_no_activity_statement_counts_as_exact_and_balanced():
    result = measure([], [], reconciliation_status="balanced")
    assert result["accuracy"] == 1
    assert result["missing"] == result["extra"] == 0
    assert passes_gates([result])


def test_family_report_aggregates_variants_and_keeps_failures_visible():
    expected = ground_truth(LAYOUTS[0])
    good = measure(expected, expected, reconciliation_status="balanced")
    bad = measure(expected, expected[:-1], reconciliation_status="balanced")
    false_alarm = measure(expected, expected, reconciliation_status="not_balanced")
    families = per_family([{"family": "chase", "bank": "Chase", **r} for r in (good, bad, false_alarm)])
    assert len(families) == 1
    family = families[0]
    assert family["statements"] == 3
    assert family["balance_rate"] == pytest.approx(2 / 3)
    assert family["accuracy"] == pytest.approx(35 / 36)
    assert family["missing"] == 1 and family["extra"] == 0
    assert family["silent_errors"] == family["false_alarms"] == 1
    table = report_table(families)
    assert "Balance rate" in table and "Silent errors" in table and "False alarms" in table


def test_corpus_contains_original_layouts_card_families_and_required_variations():
    assert len(LAYOUTS) == 10
    assert {layout.slug for layout in CARD_LAYOUTS} == {
        "chase-card", "citi-card", "capital-one-card", "american-express-card",
    }
    assert {layout.variation for layout in VARIATION_LAYOUTS} == {
        "year-boundary", "year-boundary-end-year", "multiline", "page-break", "no-activity",
        "overdraft", "million", "40-pages",
    }
    assert all(layout.pages <= 100 for layout in CORPUS_LAYOUTS)


def test_forty_page_fixture_has_rows_on_every_page_and_repeated_headers(tmp_path):
    import pdfplumber

    layout = next(layout for layout in CORPUS_LAYOUTS if layout.variation == "40-pages")
    path, expected = render(layout, tmp_path)
    assert len(expected) == 160
    with pdfplumber.open(path) as document:
        assert len(document.pages) == 40
        for page in document.pages:
            text = page.extract_text()
            assert "Transaction Date" in text and "Posting Date" in text
            assert "SYNTHETIC" in text
            assert len(page.extract_tables()[0]) == 5  # Header plus four real rows.


def test_independent_source_totals_obey_both_equations():
    for layout in CORPUS_LAYOUTS:
        totals = printed_totals(layout, ground_truth(layout))
        if layout.account_type == "card":
            assert totals["previous_balance"] - totals["payments_credits"] + totals["purchases"] + totals["fees"] + totals["interest"] == totals["new_balance"]
        else:
            assert totals["opening_balance"] + totals["money_in"] - totals["money_out"] == totals["closing_balance"]
