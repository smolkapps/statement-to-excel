import io
import json
from decimal import Decimal

from openpyxl import load_workbook

from statement_to_excel.transaction import Transaction
from statement_to_excel.writers import (
    to_csv_str,
    to_json_str,
    to_xlsx_bytes,
)


def _sample():
    return [
        Transaction(
            "2024-01-05", "PAYROLL", Decimal("3250.00"), balance=Decimal("5250.00")
        ),
        Transaction(
            "2024-01-08", "WHOLE FOODS", Decimal("-84.21"), balance=Decimal("5165.79")
        ),
    ]


def test_csv_header_and_values():
    csv = to_csv_str(_sample())
    lines = csv.strip().splitlines()
    assert lines[0] == "date,description,amount,balance,currency,type"
    assert lines[1] == "2024-01-05,PAYROLL,3250.00,5250.00,USD,credit"
    assert lines[2].endswith("-84.21,5165.79,USD,debit")


def test_json_structure_and_exact_decimals():
    data = json.loads(to_json_str(_sample()))
    assert "transactions" in data
    assert data["transactions"][0]["amount"] == "3250.00"
    assert data["transactions"][1]["amount"] == "-84.21"


def test_xlsx_has_two_sheets_and_numeric_cells():
    raw = to_xlsx_bytes(_sample())
    wb = load_workbook(io.BytesIO(raw))
    assert wb.sheetnames == ["Transactions", "Summary"]
    ws = wb["Transactions"]
    # header
    assert [c.value for c in ws[1]] == [
        "Date",
        "Description",
        "Amount",
        "Balance",
        "Currency",
        "Type",
    ]
    # amount cell is a real number, not a string
    amount_cell = ws.cell(row=2, column=3).value
    assert isinstance(amount_cell, (int, float))
    assert abs(amount_cell - 3250.00) < 1e-9
    # summary nets out
    summ = wb["Summary"]
    rows = {r[0].value: r[1].value for r in summ.iter_rows(min_row=2)}
    assert rows["Transactions"] == 2
    assert abs(rows["Net"] - (3250.00 - 84.21)) < 1e-9


def test_xlsx_empty_list_still_valid():
    raw = to_xlsx_bytes([])
    wb = load_workbook(io.BytesIO(raw))
    assert "Transactions" in wb.sheetnames
