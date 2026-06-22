from decimal import Decimal

from statement_to_excel.transaction import Transaction


def test_type_derived_from_sign():
    assert Transaction("2024-01-01", "x", Decimal("-5")).type == "debit"
    assert Transaction("2024-01-01", "x", Decimal("5")).type == "credit"
    assert Transaction("2024-01-01", "x", Decimal("0")).type == "credit"


def test_coercion_and_strip():
    t = Transaction("2024-01-01", "  spaced  ", "-1234.5", balance="100")
    assert t.amount == Decimal("-1234.5")
    assert t.balance == Decimal("100")
    assert t.description == "spaced"


def test_roundtrip_dict():
    t = Transaction("2024-01-01", "Coffee", Decimal("-4.50"), balance=Decimal("95.50"))
    d = t.to_dict()
    assert d == {
        "date": "2024-01-01",
        "description": "Coffee",
        "amount": "-4.50",
        "balance": "95.50",
        "currency": "USD",
        "type": "debit",
    }
    back = Transaction.from_dict(d)
    assert back == t


def test_dec_str_normalizes_negative_zero():
    t = Transaction("2024-01-01", "x", Decimal("-0.0"))
    assert t.to_dict()["amount"] == "0"
