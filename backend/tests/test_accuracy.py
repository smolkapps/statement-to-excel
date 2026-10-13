"""Strict end-to-end PDF accuracy gates and metric correctness."""

from copy import deepcopy

import pytest

from statement_to_excel.engine import convert_pdf
from tests.accuracy_harness import LAYOUTS, ground_truth, measure, render


@pytest.mark.parametrize("layout", LAYOUTS, ids=lambda layout: layout.slug)
def test_bank_inspired_pdf_exact_rows(layout, tmp_path):
    path, expected = render(layout, tmp_path)
    actual = [transaction.to_dict() for transaction in convert_pdf(path)]
    result = measure(expected, actual)
    assert result["accuracy"] == 1.0, (layout.bank, result, actual, expected)


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
    assert measure(expected, actual)["accuracy"] < 1


def test_accuracy_generation_reproducible(tmp_path):
    for layout in LAYOUTS:
        path, expected = render(layout, tmp_path)
        first = path.read_bytes()
        path, again = render(layout, tmp_path)
        assert path.read_bytes() == first
        assert expected == again
