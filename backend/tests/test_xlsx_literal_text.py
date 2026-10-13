"""Statement text must remain literal in the downloaded Excel workbook."""
import io
from decimal import Decimal

from openpyxl import load_workbook

from statement_to_excel.transaction import Transaction
from statement_to_excel.writers import to_xlsx_bytes


def test_formula_looking_description_remains_exact_literal_text():
    description = '=HYPERLINK("https://example.test", "synthetic merchant")'
    transaction = Transaction(date="2026-01-02", description=description, amount=Decimal("-5.00"), balance=Decimal("95.00"), currency="USD")
    workbook = load_workbook(io.BytesIO(to_xlsx_bytes([transaction])))
    cell = workbook["Transactions"]["B2"]
    assert cell.value == description
    assert cell.data_type == "s"
    assert workbook["Transactions"]["C2"].value == -5
