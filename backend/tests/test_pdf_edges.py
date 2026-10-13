"""Synthetic PDFs verify safe failure and multi-page ledger boundaries."""

from io import BytesIO

import pytest
from PIL import Image
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle

from statement_to_excel.engine import ConversionError, convert_pdf, convert_text
from statement_to_excel.parsers import parse_date


def _pdf(draw, *, encrypt=None):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=LETTER, invariant=1, encrypt=encrypt)
    draw(c)
    c.save()
    buffer.seek(0)
    return buffer


def _text_page(c, account="0000"):
    c.drawString(40, 750, "Synthetic account statement - January 2024")
    c.drawString(40, 730, f"Account ending {account}")
    c.drawString(40, 710, "01/05/2024 SYNTHETIC PAYROLL 100.00 100.00")


def test_password_protected_pdf_clear_error():
    # A generated test password, never an account credential or customer file.
    pdf = _pdf(_text_page, encrypt=StandardEncryption("synthetic-fixture-password"))
    with pytest.raises(ConversionError, match="Password-protected.*Unlock it locally"):
        convert_pdf(pdf)


def test_scanned_image_without_text_layer_clear_error():
    def draw(c):
        c.drawImage(ImageReader(Image.new("RGB", (100, 100), "white")), 40, 400, 500, 300)
    with pytest.raises(ConversionError, match="scanned/image-only"):
        convert_pdf(_pdf(draw))


def test_mixed_scanned_and_text_pdf_does_not_silently_omit_page():
    def draw(c):
        _text_page(c)
        c.showPage()
        c.drawImage(ImageReader(Image.new("RGB", (100, 100), "white")), 40, 400, 500, 300)
    with pytest.raises(ConversionError, match="mixed scanned/text PDFs"):
        convert_pdf(_pdf(draw))


def test_scanned_body_beneath_selectable_header_not_silently_omitted():
    def draw(c):
        _text_page(c)
        c.showPage()
        c.drawString(40, 750, "Synthetic statement - January 2024")
        c.drawString(40, 730, "Account ending 0000")
        c.drawImage(ImageReader(Image.new("RGB", (100, 100), "white")), 40, 400, 500, 300)
    with pytest.raises(ConversionError, match="scanned body beneath selectable headers"):
        convert_pdf(_pdf(draw))


@pytest.mark.parametrize("label", ["Account ending", "Account ending in", "Account number:", "Checking Account:", "Savings Account #"])
def test_distinct_account_ledgers_rejected_clearly(label):
    def draw(c):
        for account in ("xxxx1111", "xxxx2222"):
            c.drawString(40, 750, "Synthetic statement - January 2024")
            c.drawString(40, 730, f"{label} {account}")
            c.drawString(40, 710, "01/05/2024 SYNTHETIC PAYROLL 100.00 100.00")
            c.showPage()
    with pytest.raises(ConversionError, match="Multiple accounts.*separately"):
        convert_pdf(_pdf(draw))


def test_same_account_mixed_layout_pages_all_rows_and_signs_preserved():
    def draw(c):
        c.drawString(40, 750, "Synthetic statement - January 2024")
        c.drawString(40, 730, "Account ending 0000")
        table = Table([
            ["Date", "Description", "Debit", "Credit", "Balance"],
            ["01/02/2024", "SYNTHETIC PAYROLL", "", "100.00", "100.00"],
            ["01/03/2024", "SYNTHETIC RENT", "40.00", "", "60.00"],
        ], colWidths=[75, 190, 60, 60, 70])
        table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .5, "black")]))
        _, height = table.wrapOn(c, 500, 500)
        table.drawOn(c, 40, 700 - height)
        c.showPage()
        c.drawString(40, 750, "Synthetic statement - January 2024")
        c.drawString(40, 730, "Account ending 0000")
        c.drawString(40, 710, "Date Description Amount Balance")
        c.drawString(40, 690, "01/04/2024 SYNTHETIC GROCERY 10.00 50.00")
        c.drawString(40, 670, "01/05/2024 SYNTHETIC REFUND 20.00 70.00")
    rows = convert_pdf(_pdf(draw))
    assert [r.description for r in rows] == ["SYNTHETIC PAYROLL", "SYNTHETIC RENT", "SYNTHETIC GROCERY", "SYNTHETIC REFUND"]
    assert [str(r.amount) for r in rows] == ["100.00", "-40.00", "-10.00", "20.00"]
    assert [str(r.balance) for r in rows] == ["100.00", "60.00", "50.00", "70.00"]


def test_invalid_pdf_clear_error():
    with pytest.raises(ConversionError, match="Invalid or damaged PDF"):
        convert_pdf(BytesIO(b"not a PDF"))


def test_short_numeric_dates_require_statement_year():
    assert parse_date("01/05") is None
    assert parse_date("01/05", default_year=2024) == "2024-01-05"
    assert parse_date("31/01", default_year=2024, dayfirst=True) == "2024-01-31"
    assert parse_date("02/30", default_year=2024) is None


def test_integer_reference_is_description_not_amount_or_balance():
    rows = convert_text(lines=["01/05/2024 SYNTHETIC BATCH 42 -12.34"])
    assert rows[0].description == "SYNTHETIC BATCH 42"
    assert str(rows[0].amount) == "-12.34"
    assert rows[0].balance is None
