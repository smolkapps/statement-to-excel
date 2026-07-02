"""The conversion engine: PDF / text -> normalized :class:`Transaction` list.

Design goals
------------
* **One thing, done well.** Turn a *checking / credit-card statement* PDF into a
  clean transaction table. We do not try to be a general OCR system.
* **Layout-agnostic.** Two complementary strategies run and the better result
  wins:

  1. ``_from_tables`` — uses pdfplumber's ruled-table extraction, then finds the
     column that is mostly dates and the column that is mostly amounts.
  2. ``_from_lines`` — a regex line scanner for borderless statements where each
     transaction is ``<date> <description...> <amount> [balance]`` on one line,
     with continuation lines folded into the previous description.

* **Deterministic & exact on money.** Everything is :class:`decimal.Decimal`.

The public entry points are :func:`convert_text` (operate on already-extracted
page text, used by the tests with synthetic fixtures) and :func:`convert_pdf`
(reads a real PDF via pdfplumber).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Sequence

from .parsers import looks_like_amount, looks_like_date, parse_amount, parse_date
from .transaction import Transaction

__all__ = ["convert_text", "convert_pdf", "ConversionError", "StatementSummary"]


class ConversionError(Exception):
    """Raised when no transactions can be extracted from the input."""


@dataclass
class StatementSummary:
    """Roll-up totals computed from a list of transactions."""

    count: int
    total_debit: Decimal  # sum of negative amounts, reported as a positive number
    total_credit: Decimal  # sum of positive amounts
    net: Decimal
    currency: str
    start_date: Optional[str]
    end_date: Optional[str]

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "total_debit": f"{self.total_debit:f}",
            "total_credit": f"{self.total_credit:f}",
            "net": f"{self.net:f}",
            "currency": self.currency,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }


def summarize(txns: Sequence[Transaction], currency: str = "USD") -> StatementSummary:
    """Compute debit/credit/net totals and the date range for ``txns``."""
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for t in txns:
        if t.amount < 0:
            total_debit += -t.amount
        else:
            total_credit += t.amount
    dates = sorted(t.date for t in txns if t.date)
    cur = txns[0].currency if txns else currency
    return StatementSummary(
        count=len(txns),
        total_debit=total_debit,
        total_credit=total_credit,
        net=total_credit - total_debit,
        currency=cur,
        start_date=dates[0] if dates else None,
        end_date=dates[-1] if dates else None,
    )


# --------------------------------------------------------------------------- #
# Year inference (for "Mon DD" style statements that omit the year per-row)
# --------------------------------------------------------------------------- #
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _infer_year(text: str) -> Optional[int]:
    """Pull a plausible statement year out of the header text, if present."""
    years = [int(m.group(0)) for m in _YEAR_RE.finditer(text)]
    if not years:
        return None
    # The most frequent year wins; ties resolved by the latest.
    years.sort()
    best = max(set(years), key=lambda y: (years.count(y), y))
    return best


def _infer_dayfirst(text: str) -> bool:
    """Heuristic: treat dd/mm as day-first only when a date is unambiguous."""
    # If any numeric date has a first component > 12, it must be day-first.
    for m in re.finditer(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.]\d{2,4}\b", text):
        if int(m.group(1)) > 12 >= int(m.group(2)):
            return True
    return False


# --------------------------------------------------------------------------- #
# Strategy 1: ruled tables
# --------------------------------------------------------------------------- #
def _from_tables(
    tables: Sequence[Sequence[Sequence[Optional[str]]]],
    *,
    currency: str,
    dayfirst: bool,
    default_year: Optional[int],
) -> List[Transaction]:
    out: List[Transaction] = []
    for table in tables:
        rows = [[(c or "").strip() for c in row] for row in table if row]
        if len(rows) < 2:
            continue
        ncols = max(len(r) for r in rows)
        rows = [r + [""] * (ncols - len(r)) for r in rows]

        # Score each column for "date-ness" and "amount-ness" across body rows.
        body = rows[1:]
        date_score = [0] * ncols
        amt_score = [0] * ncols
        for r in body:
            for j in range(ncols):
                cell = r[j]
                if looks_like_date(cell, dayfirst=dayfirst, default_year=default_year):
                    date_score[j] += 1
                if looks_like_amount(cell):
                    amt_score[j] += 1
        if max(date_score) == 0 or max(amt_score) == 0:
            continue

        date_col = max(range(ncols), key=lambda j: date_score[j])

        header = [h.lower() for h in rows[0]]
        debit_col = _find_header(header, ("debit", "withdrawal", "payment", "charge"))
        credit_col = _find_header(header, ("credit", "deposit"))
        balance_col = _find_header(header, ("balance",))
        amount_col = _find_header(header, ("amount", "value"))
        if amount_col is None:
            # pick the amount-iest column that isn't date/debit/credit/balance
            taken = {date_col, debit_col, credit_col, balance_col}
            cands = [j for j in range(ncols) if j not in taken and amt_score[j] > 0]
            amount_col = max(cands, key=lambda j: amt_score[j]) if cands else None

        desc_col = _guess_description_col(
            ncols, {date_col, debit_col, credit_col, balance_col, amount_col}, body
        )

        for r in body:
            iso = parse_date(r[date_col], dayfirst=dayfirst, default_year=default_year)
            if not iso:
                continue
            amount = _row_amount(r, debit_col, credit_col, amount_col)
            if amount is None:
                continue
            balance = parse_amount(r[balance_col]) if balance_col is not None else None
            desc = r[desc_col] if desc_col is not None else ""
            out.append(
                Transaction(
                    date=iso,
                    description=desc,
                    amount=amount,
                    balance=balance,
                    currency=currency,
                )
            )
    return out


def _find_header(header: Sequence[str], keys: Sequence[str]) -> Optional[int]:
    for j, h in enumerate(header):
        for k in keys:
            if k in h:
                return j
    return None


def _guess_description_col(ncols, taken, body) -> Optional[int]:
    """The description is the widest free-text column not used for numbers."""
    best, best_len = None, -1
    for j in range(ncols):
        if j in taken:
            continue
        avg = _avg_text_len(body, j)
        if avg > best_len:
            best, best_len = j, avg
    return best


def _avg_text_len(body, j) -> float:
    vals = [len(r[j]) for r in body if j < len(r)]
    return sum(vals) / len(vals) if vals else 0.0


def _row_amount(row, debit_col, credit_col, amount_col) -> Optional[Decimal]:
    """Resolve a signed amount from either a single amount column or a
    debit/credit pair (debit => negative)."""
    if debit_col is not None or credit_col is not None:
        debit = parse_amount(row[debit_col]) if debit_col is not None else None
        credit = parse_amount(row[credit_col]) if credit_col is not None else None
        if debit is not None and debit != 0:
            return -abs(debit)
        if credit is not None and credit != 0:
            return abs(credit)
        # both empty/zero -> fall through to amount_col if any
    if amount_col is not None:
        return parse_amount(row[amount_col])
    return None


# --------------------------------------------------------------------------- #
# Strategy 2: borderless text lines
# --------------------------------------------------------------------------- #
# Leading date token, then the rest of the line. We grab trailing amounts later.
_LEADING_DATE_RE = re.compile(
    r"^\s*("
    r"\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}"  # 01/02/2024, 2024-01-02
    r"|[A-Za-z]{3,9}\.?\s+\d{1,2}(?:,?\s*\d{4})?"  # Jan 5 / Jan 5, 2024
    r"|\d{1,2}\s+[A-Za-z]{3,9}\.?(?:\s+\d{4})?"  # 5 Jan 2024
    r")\s+(.*\S)\s*$"
)
# A dated "OPENING/BEGINNING BALANCE" line carrying a single number states the
# starting balance, not a transaction. We use it to seed the running balance.
_BALANCE_SEED_RE = re.compile(r"\b(?:opening|beginning)\b.*\bbalance\b", re.IGNORECASE)
# One amount token (currency/sign/parens aware) used to peel trailing numbers.
_AMOUNT_TOKEN_RE = re.compile(
    r"(?:[$£€¥₩]|R\$|HK\$|US\$)?\s*"
    r"(?:\(|\+|-)?\s*"
    r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+\.\d+"
)


def _apply_balance_delta_sign(
    amount: Decimal, balance: Optional[Decimal], prev_balance: Optional[Decimal]
) -> Decimal:
    """Re-sign ``amount`` from the running-balance movement, when we can trust it.

    Borderless statements list amounts as bare, unsigned trailing numbers, so a
    withdrawal and a deposit are indistinguishable from the amount token alone —
    the naive parse types every row a credit. When a row carries a running
    balance *and* we know the previous row's balance, the movement can be
    authoritative: a balance that dropped is money out (debit => negative), one
    that rose is money in (credit => positive).

    But the movement is only trustworthy when its magnitude actually matches this
    row's amount (within a cent). A mismatch means the balance chain is broken —
    a preceding row carried no balance, so ``prev_balance`` is stale and this
    delta spans *two* transactions — or the statement is newest-first, where the
    delta reflects a neighbouring row rather than this one. Re-signing on a bogus
    delta would silently flip an explicitly-signed amount (parens, trailing DR,
    leading minus). So when the magnitudes disagree we decline and keep the
    parsed sign. If the balance is flat or either balance is missing we likewise
    leave the amount as parsed.
    """
    if balance is None or prev_balance is None:
        return amount
    delta = balance - prev_balance
    # Only trust the movement when |delta| ~= |amount|; otherwise the chain is
    # broken/stale (or reverse-chronological) and the parsed sign is safer.
    if abs(abs(delta) - abs(amount)) > Decimal("0.01"):
        return amount
    if delta < 0:
        return -abs(amount)
    if delta > 0:
        return abs(amount)
    return amount


def _from_lines(
    lines: Sequence[str],
    *,
    currency: str,
    dayfirst: bool,
    default_year: Optional[int],
) -> List[Transaction]:
    out: List[Transaction] = []
    prev_balance: Optional[Decimal] = None
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        m = _LEADING_DATE_RE.match(line)
        if not m:
            # Continuation line: fold into the previous transaction's memo.
            if out and not _AMOUNT_TOKEN_RE.search(line):
                extra = line.strip()
                if extra:
                    out[-1].description = (out[-1].description + " " + extra).strip()
            continue

        date_tok, rest = m.group(1), m.group(2)
        iso = parse_date(date_tok, dayfirst=dayfirst, default_year=default_year)
        if not iso:
            continue

        amounts = _trailing_amounts(rest)
        if not amounts:
            continue
        # Last trailing number is balance IF there are >=2 numbers; otherwise the
        # single trailing number is the transaction amount.
        if len(amounts) >= 2:
            amount_str, balance_str = amounts[-2], amounts[-1]
            balance = parse_amount(balance_str)
            n_strip = 2
        else:
            amount_str, balance = amounts[-1], None
            n_strip = 1

        desc = _strip_trailing_numbers(rest, n_strip)

        # A dated "OPENING/BEGINNING BALANCE" line carrying a single number is the
        # starting balance, not a transaction: seed the running balance from it
        # (so the first real row's sign can be inferred) and emit nothing.
        if n_strip == 1 and _BALANCE_SEED_RE.search(desc):
            seed = parse_amount(amount_str)
            if seed is not None:
                prev_balance = seed
                continue

        amount = parse_amount(amount_str)
        if amount is None:
            continue

        # Borderless rows have no explicit debit/credit column, so infer the
        # sign from how the running balance moved rather than trusting the bare
        # (always-positive) amount token.
        amount = _apply_balance_delta_sign(amount, balance, prev_balance)
        if balance is not None:
            prev_balance = balance
        out.append(
            Transaction(
                date=iso,
                description=desc,
                amount=amount,
                balance=balance,
                currency=currency,
            )
        )
    return out


def _trailing_amounts(rest: str) -> List[str]:
    """Return the run of amount-looking tokens at the END of ``rest``."""
    tokens = rest.split()
    trailing: List[str] = []
    for tok in reversed(tokens):
        if looks_like_amount(tok):
            trailing.append(tok)
        else:
            break
    trailing.reverse()
    return trailing


def _strip_trailing_numbers(rest: str, n: int) -> str:
    tokens = rest.split()
    if n <= 0:
        return rest.strip()
    return " ".join(tokens[:-n]).strip()


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def convert_text(
    *,
    full_text: str = "",
    lines: Optional[Sequence[str]] = None,
    tables: Optional[Sequence[Sequence[Sequence[Optional[str]]]]] = None,
    currency: str = "USD",
    dayfirst: Optional[bool] = None,
    default_year: Optional[int] = None,
) -> List[Transaction]:
    """Convert already-extracted statement content into transactions.

    Pass any combination of ``full_text`` (used for year / day-first inference),
    ``lines`` (for the borderless strategy) and ``tables`` (for the ruled-table
    strategy). Ruled tables win when they parse (see :func:`_choose_strategy`),
    otherwise the line scanner is used. Raises :class:`ConversionError` if
    neither finds anything.
    """
    hint_text = full_text or ("\n".join(lines) if lines else "")
    if default_year is None:
        default_year = _infer_year(hint_text)
    if dayfirst is None:
        dayfirst = _infer_dayfirst(hint_text)

    table_txns: List[Transaction] = []
    if tables:
        table_txns = _from_tables(
            tables, currency=currency, dayfirst=dayfirst, default_year=default_year
        )

    line_txns: List[Transaction] = []
    if lines:
        line_txns = _from_lines(
            lines, currency=currency, dayfirst=dayfirst, default_year=default_year
        )

    chosen = _choose_strategy(table_txns, line_txns)
    if not chosen:
        raise ConversionError(
            "No transactions found. The statement may be image-only (needs OCR) "
            "or use an unsupported layout."
        )
    return chosen


def _choose_strategy(
    table_txns: List[Transaction], line_txns: List[Transaction]
) -> List[Transaction]:
    """Pick the better of the two extraction strategies.

    Ruled tables are *authoritative* when they parse, because they capture
    column semantics the line scanner cannot — most importantly separate
    debit/credit columns, which the line strategy can only see as unsigned
    trailing numbers. So we prefer the table result whenever it recovered a
    reasonable share of the rows. We only fall back to the line strategy when
    the table extraction clearly fragmented (found fewer than ~70% of the rows
    the line scanner did) or found nothing at all.
    """
    nt, nl = len(table_txns), len(line_txns)
    if nt == 0:
        return line_txns
    if nl == 0:
        return table_txns
    # Table extraction is preferred unless it captured far fewer rows than lines.
    if nt >= 0.7 * nl:
        return table_txns
    return line_txns


def convert_pdf(
    path,
    *,
    currency: str = "USD",
    dayfirst: Optional[bool] = None,
    default_year: Optional[int] = None,
) -> List[Transaction]:
    """Read a *text-based* PDF at ``path`` and return its transactions.

    Requires the optional ``pdfplumber`` dependency. For scanned / image-only
    PDFs this raises :class:`ConversionError` (run OCR first — out of scope).
    """
    try:
        import pdfplumber  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only without dep
        raise ConversionError(
            "pdfplumber is required to read PDFs. Install with: pip install pdfplumber"
        ) from exc

    all_lines: List[str] = []
    all_tables: List[List[List[Optional[str]]]] = []
    text_parts: List[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            text_parts.append(txt)
            all_lines.extend(txt.splitlines())
            for tbl in page.extract_tables() or []:
                all_tables.append(tbl)

    full_text = "\n".join(text_parts)
    if not full_text.strip() and not all_tables:
        raise ConversionError(
            "No extractable text in PDF (likely a scanned/image-only file). "
            "Run OCR first; OCR is out of scope for this tool."
        )

    return convert_text(
        full_text=full_text,
        lines=all_lines,
        tables=all_tables,
        currency=currency,
        dayfirst=dayfirst,
        default_year=default_year,
    )
