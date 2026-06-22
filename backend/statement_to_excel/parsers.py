"""Conservative parsing helpers for dates and monetary amounts.

Each function returns ``None`` when a token cannot be confidently parsed rather
than guessing, so callers can treat a successful parse as a *signal* that a cell
really is a date / amount. That property is what lets the engine auto-detect the
transaction block in an arbitrary statement layout.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

__all__ = [
    "parse_date",
    "parse_amount",
    "looks_like_amount",
    "looks_like_date",
]

# Month name -> month number, covering 3-letter abbreviations and full names.
_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

# Numeric date with separators "/", "-" or ".".
_NUM_DATE_RE = re.compile(
    r"^\s*(\d{1,4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,4})\s*$"
)

# "Mon DD" / "Mon DD YYYY" / "Mon DD, YYYY"  e.g. "Jan 05", "Mar 3, 2024"
_MON_DAY_RE = re.compile(r"^\s*([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:\s*,?\s*(\d{4}))?\s*$")

# "DD Mon YYYY" / "DD Mon"  e.g. "05 Jan 2024", "3 March"
_DAY_MON_RE = re.compile(r"^\s*(\d{1,2})\s+([A-Za-z]{3,9})\.?(?:\s+(\d{4}))?\s*$")


def _make_date(year: int, month: int, day: int) -> Optional[str]:
    """Build an ISO date string, returning None on any invalid combination."""
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _normalize_year(y: int) -> int:
    """Expand a possibly 2-digit year to 4 digits (POSIX strptime 69 pivot)."""
    if y >= 100:
        return y
    return 2000 + y if y < 69 else 1900 + y


def parse_date(
    text: str,
    *,
    dayfirst: bool = False,
    default_year: Optional[int] = None,
) -> Optional[str]:
    """Parse a date token into an ISO ``YYYY-MM-DD`` string, or ``None``.

    Supported formats:
      * ``MM/DD/YYYY`` (US, default) and ``DD/MM/YYYY`` (``dayfirst=True``)
      * ``YYYY-MM-DD`` (ISO, auto-detected by a 4-digit leading group)
      * ``Mon DD`` / ``Mon DD, YYYY`` / ``Mon DD YYYY``
      * ``DD Mon YYYY`` / ``DD Mon``
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None

    m = _NUM_DATE_RE.match(s)
    if m:
        a, b, c = (int(g) for g in m.groups())
        if len(m.group(1)) == 4:  # leading 4-digit group => ISO YYYY-MM-DD
            return _make_date(a, b, c)
        year = _normalize_year(c)
        day, month = (a, b) if dayfirst else (b, a)
        return _make_date(year, month, day)

    m = _MON_DAY_RE.match(s)
    if m:
        mon = _MONTHS.get(m.group(1).lower())
        if mon is not None:
            day = int(m.group(2))
            year = int(m.group(3)) if m.group(3) else default_year
            if year is None:
                return None
            return _make_date(year, mon, day)

    m = _DAY_MON_RE.match(s)
    if m:
        mon = _MONTHS.get(m.group(2).lower())
        if mon is not None:
            day = int(m.group(1))
            year = int(m.group(3)) if m.group(3) else default_year
            if year is None:
                return None
            return _make_date(year, mon, day)

    return None


# Amount: optional sign / parens, optional currency symbol, digits with optional
# thousands separators, optional decimal part, optional trailing minus or DR/CR.
_AMOUNT_CORE = r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?"
_AMOUNT_RE = re.compile(
    r"^\s*"
    r"(?P<open>\()?"
    r"\s*(?P<sign>[+-])?"
    r"\s*(?P<cur>[$£€¥₩]|R\$|HK\$|US\$)?\s*"
    r"(?P<num>" + _AMOUNT_CORE + r")"
    r"\s*(?P<close>\))?"
    r"\s*(?P<trailmin>-)?"
    r"\s*(?P<drcr>DR|CR)?"
    r"\s*$",
    re.IGNORECASE,
)


def parse_amount(text: str) -> Optional[Decimal]:
    """Parse a monetary token into a signed :class:`Decimal`, or ``None``.

    Handles ``$1,234.56``, ``(1,234.56)`` and ``1,234.56-`` (both negative),
    leading ``+``/``-``, currency symbols, and trailing ``DR``/``CR`` markers
    (``DR`` => negative, ``CR`` => positive).
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None

    m = _AMOUNT_RE.match(s)
    if not m:
        return None

    # A lone open paren without a matching close (or vice-versa) is malformed.
    if bool(m.group("open")) != bool(m.group("close")):
        return None

    num = m.group("num").replace(",", "")
    try:
        value = Decimal(num)
    except InvalidOperation:
        return None

    negative = False
    if m.group("open") and m.group("close"):
        negative = True
    if m.group("trailmin"):
        negative = True
    if m.group("sign") == "-":
        negative = True
    if (m.group("drcr") or "").upper() == "DR":
        negative = True

    return -value if negative else value


def looks_like_amount(text: str) -> bool:
    """True if ``text`` parses as an amount AND contains at least one digit."""
    if text is None:
        return False
    return parse_amount(text) is not None and any(c.isdigit() for c in str(text))


def looks_like_date(
    text: str, *, dayfirst: bool = False, default_year: Optional[int] = None
) -> bool:
    """True if ``text`` parses as a date in any supported format."""
    return parse_date(text, dayfirst=dayfirst, default_year=default_year) is not None
