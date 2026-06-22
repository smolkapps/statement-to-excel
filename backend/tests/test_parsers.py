from decimal import Decimal

import pytest

from statement_to_excel.parsers import (
    looks_like_amount,
    looks_like_date,
    parse_amount,
    parse_date,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("01/05/2024", "2024-01-05"),  # US MM/DD
        ("2024-01-05", "2024-01-05"),  # ISO
        ("Jan 5, 2024", "2024-01-05"),
        ("Jan 5", None),  # no year, no default
        ("5 Jan 2024", "2024-01-05"),
        ("12/31/2024", "2024-12-31"),
        ("13/31/2024", None),  # invalid month in US order
        ("02/30/2024", None),  # invalid day
        ("garbage", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_date_us(text, expected):
    assert parse_date(text) == expected


def test_parse_date_dayfirst_and_default_year():
    assert parse_date("31/01/2024", dayfirst=True) == "2024-01-31"
    assert parse_date("Mar 7", default_year=2024) == "2024-03-07"
    assert parse_date("07/06/24") == "2024-07-06"  # 2-digit year expands


@pytest.mark.parametrize(
    "text,expected",
    [
        ("$1,234.56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")),
        ("(1,234.56)", Decimal("-1234.56")),
        ("1,234.56-", Decimal("-1234.56")),
        ("-42", Decimal("-42")),
        ("+42.00", Decimal("42.00")),
        ("100.00 DR", Decimal("-100.00")),
        ("100.00 CR", Decimal("100.00")),
        ("€9,99", None),  # comma-decimal not supported -> reject, don't guess
        ("(50", None),  # unbalanced paren rejected
        ("50)", None),
        ("abc", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


def test_looks_like_helpers():
    assert looks_like_amount("$10.00")
    assert not looks_like_amount("hello")
    assert not looks_like_amount("")
    assert looks_like_date("01/02/2024")
    assert not looks_like_date("not a date")
