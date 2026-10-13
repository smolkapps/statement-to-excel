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
from .reconciliation import Reconciliation, reconcile

__all__ = ["convert_text", "convert_pdf", "ConversionError", "StatementSummary",
           "StatementTransactions", "extract_totals"]


class StatementTransactions(list[Transaction]):
    """A backwards-compatible transaction list with statement-level evidence."""

    def __init__(self, rows, *, reconciliation: Reconciliation, layout: str):
        super().__init__(rows)
        self.reconciliation = reconciliation
        self.layout = layout


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
_YEAR_RE = re.compile(r"(?<![\d.,])\b(19|20)\d{2}\b(?![.,]\d)")
_ACCOUNT_HEADER_RE = re.compile(
    r"^\s*(?:(?:checking|savings|credit\s+card)\s+)?account\s*"
    r"(?:number|no\.?|#|ending(?:\s+in)?)?\s*[:#]?\s*"
    r"([xX*•\d][xX*•\d -]{2,}\d)\b", re.IGNORECASE | re.MULTILINE
)


def _assert_single_account(text: str) -> None:
    """Never combine identifiable account ledgers without account attribution."""
    accounts = {re.sub(r"[\s-]", "", match.group(1)).lower()
                for match in _ACCOUNT_HEADER_RE.finditer(text)}
    if len(accounts) > 1:
        raise ConversionError(
            "Multiple accounts detected. Convert each account's statement separately; "
            "combined multi-account statements are not supported."
        )


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


_FULL_DATE_TOKEN = (r"(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"
                    r"|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}"
                    r"|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}"
                    r"|\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{4})")


def _statement_period(text: str, dayfirst: bool) -> Optional[tuple[str, str]]:
    """Read an explicit header period, rather than guessing from transaction years."""
    for line in text.splitlines():
        if not re.search(r"period|cycle|statement\s+(?:dates|from)|\bthrough\b", line, re.I):
            continue
        dates = [parse_date(match.group(), dayfirst=dayfirst)
                 for match in re.finditer(_FULL_DATE_TOKEN, line)]
        dates = [date for date in dates if date]
        if len(dates) >= 2 and dates[0] <= dates[1]:
            return dates[0], dates[1]
        # Many statements print the year once: December 20 - January 19, 2024.
        endpoints = re.split(r"\s+(?:-|–|—|to|through)\s+", line, flags=re.I)
        if len(endpoints) == 2:
            end_match = re.search(_FULL_DATE_TOKEN, endpoints[1])
            start_match = re.search(
                r"(?:\d{1,2}[-/.]\d{1,2}|[A-Za-z]{3,9}\.?\s+\d{1,2}"
                r"|\d{1,2}\s+[A-Za-z]{3,9}\.?)\s*$", endpoints[0])
            if end_match and start_match:
                end = parse_date(end_match.group(), dayfirst=dayfirst)
                if end:
                    start = parse_date(start_match.group(), dayfirst=dayfirst,
                                       default_year=int(end[:4]))
                    if start and start > end:
                        start = parse_date(start_match.group(), dayfirst=dayfirst,
                                           default_year=int(end[:4]) - 1)
                    if start:
                        return start, end
    return None


def _statement_date(token, *, dayfirst, default_year, period=None):
    """Resolve a short date inside a known December-to-January period."""
    explicit = parse_date(token, dayfirst=dayfirst)
    if explicit:
        return explicit, ()
    iso = parse_date(token, dayfirst=dayfirst,
                     default_year=int(period[1][:4]) if period else default_year)
    if iso and period and period[0][:4] != period[1][:4]:
        month_day = iso[5:]
        candidates = [f"{year}-{month_day}" for year in
                      range(int(period[0][:4]), int(period[1][:4]) + 1)]
        candidates = [date for date in candidates if period[0] <= date <= period[1]
                      and parse_date(date) is not None]
        if len(candidates) == 1:
            return candidates[0], ("year_inferred_rollover",)
    return iso, ()


_TOTAL_LABELS = {
    "opening": r"(?:opening|beginning|starting|previous|prior)\s+balance|balance\s+(?:brought|carried)\s+forward|balance\s+b/?f",
    "money_in": r"(?:total\s+)?(?:money\s+in|deposits?(?:\s*(?:and|&|/)\s*(?:other\s+)?(?:additions|credits))?|credits?|additions)",
    "money_out": r"(?:total\s+)?(?:money\s+out|withdrawals?(?:\s*(?:and|&|/)\s*(?:other\s+)?(?:debits|deductions|subtractions))?|debits?|deductions|subtractions)",
    "closing": r"(?:closing|ending|final)\s+balance",
    "previous": r"(?:previous|prior|beginning)\s+balance",
    "payments_credits": r"(?:total\s+)?payments?(?:\s*(?:and|&|/)\s*(?:other\s+)?credits?)?(?:\s+and\s+adjustments)?",
    "purchases": r"(?:total\s+)?(?:purchases?(?:\s+and\s+(?:other\s+)?charges)?|new\s+charges)",
    "fees": r"(?:total\s+)?fees?(?:\s+charged)?",
    "interest": r"(?:total\s+)?interest(?:\s+(?:charged|charges))?",
    "new": r"new\s+balance(?:\s+total)?",
}


def _account_type(text: str) -> str:
    if re.search(r"^\s*(?:[A-Za-z][A-Za-z .&'-]{0,60}\s+)?credit\s+card\s+statement\b",
                 text, re.I | re.M):
        return "card"
    if re.search(r"\bnew\s+balance\b", text, re.I) and re.search(
            r"\b(?:previous\s+balance|purchases|payments\s+and\s+credits)\b", text, re.I):
        return "card"
    return "deposit"


def _assert_transaction_dates(text, *, dayfirst, default_year, period, account_type):
    """Fail closed on financial rows whose date token is impossible/unreadable."""
    for line in text.splitlines():
        match = _LEADING_DATE_RE.match(line)
        if not match:
            continue
        token, rest = match.group(1), match.group(2)
        if account_type == "card":
            posted = _LEADING_DATE_RE.match(rest)
            if posted:
                token, rest = posted.group(1), posted.group(2)
        amounts = _trailing_amounts(rest)
        if not amounts or not any(re.search(r"[.$£€¥₩]", amount) for amount in amounts):
            continue
        iso, _ = _statement_date(token, dayfirst=dayfirst, default_year=default_year,
                                 period=period)
        if iso is None:
            raise ConversionError("A transaction date could not be read. "
                                  "Check the statement dates or provide the statement year.")


def extract_totals(text: str, *, account_type: str = "deposit") -> dict[str, Decimal | None]:
    """Extract whole-label statement summaries; never fabricate missing figures."""
    keys = (("previous", "payments_credits", "purchases", "fees", "interest", "new")
            if account_type == "card" else ("opening", "money_in", "money_out", "closing"))
    totals = {key: None for key in keys}
    found = {key: set() for key in keys}
    separate_payments, separate_credits = set(), set()
    combined_payments = False
    lines = text.splitlines()
    for index, raw in enumerate(lines):
        # Dated opening/closing balance rows are summaries, not transactions.
        line = raw.strip()
        dated = _LEADING_DATE_RE.match(line)
        if dated:
            line = dated.group(2)
            endpoints = ("previous", "new") if account_type == "card" else ("opening", "closing")
            if not any(re.match(r"^(?:" + _TOTAL_LABELS[key] + r")\b", line, re.I)
                       for key in endpoints):
                continue
        for key in keys:
            label = re.match(r"^(?:" + _TOTAL_LABELS[key] + r")\b", line, re.I)
            if not label:
                continue
            suffix = line[label.end():].strip(" :\t")
            # 'Opening balance on March 1' is a printed opening balance too.
            amounts = _trailing_amounts(suffix)
            value = parse_amount(amounts[-1]) if len(amounts) == 1 else None
            qualifier = _strip_trailing_numbers(suffix, 1) if amounts else suffix
            if qualifier:
                date_qualifier = re.match(r"^(?:on|as\s+of)\s+(.+)$", qualifier, re.I)
                if key not in ("opening", "closing", "previous", "new") or not date_qualifier \
                        or not parse_date(date_qualifier.group(1)):
                    value = None
            if not suffix and index + 1 < len(lines):
                value = parse_amount(lines[index + 1].strip())
            if value is not None:
                if key in ("money_in", "money_out", "payments_credits"):
                    value = abs(value)
                found[key].add(value)
                if key == "payments_credits":
                    if re.search(r"credits?|adjustments", label.group(), re.I):
                        combined_payments = True
                    else:
                        separate_payments.add(value)
        if account_type == "card" and not dated:
            credit_label = re.match(r"^(?:(?:other|total)\s+)?credits?\b", line, re.I)
            if credit_label:
                credit = parse_amount(line[credit_label.end():].strip(" :\t"))
                if credit is not None:
                    separate_credits.add(abs(credit))
    for key, values in found.items():
        if len(values) == 1:
            totals[key] = next(iter(values))
    if account_type == "card" and not combined_payments and len(separate_payments) == 1 \
            and len(separate_credits) == 1:
        totals["payments_credits"] = next(iter(separate_payments)) + next(iter(separate_credits))
    return totals


def _card_category(description: str, section: str = "", native_amount=None) -> str:
    if section:
        return section
    if re.search(r"\b(?:payment|credit|refund)\b", description, re.I):
        return "payment_credit"
    if re.search(r"\bfee\b", description, re.I):
        return "fee"
    if re.search(r"\binterest\b", description, re.I):
        return "interest"
    if native_amount is not None and native_amount < 0:
        return "payment_credit"
    return "purchase"


def _card_amount(amount: Decimal, category: str) -> Decimal:
    # Card statements express debt movement; normalized rows express money out.
    return abs(amount) if category == "payment_credit" else -amount


# --------------------------------------------------------------------------- #
# Strategy 1: ruled tables
# --------------------------------------------------------------------------- #
def _from_tables(
    tables: Sequence[Sequence[Sequence[Optional[str]]]],
    *,
    currency: str,
    dayfirst: bool,
    default_year: Optional[int],
    period: Optional[tuple[str, str]] = None,
    account_type: str = "deposit",
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

        header = [" ".join(h.lower().split()) for h in rows[0]]
        date_col = _find_header(header, ("posted date", "posting date", "post date"))
        if date_col is None or not date_score[date_col]:
            date_col = max(range(ncols), key=lambda j: date_score[j])
        debit_col = _find_header(header, ("debit", "withdrawal", "payment", "charge"))
        credit_col = _find_header(header, ("credit", "deposit"))
        balance_col = _find_header(header, ("balance",))
        amount_col = _find_header(header, ("amount", "value"))
        if amount_col is None:
            # pick the amount-iest column that isn't date/debit/credit/balance
            taken = {date_col, debit_col, credit_col, balance_col}
            cands = [j for j in range(ncols) if j not in taken and amt_score[j] > 0]
            amount_col = max(cands, key=lambda j: amt_score[j]) if cands else None

        desc_col = _find_header(header, ("description", "merchant", "details", "memo"))
        if desc_col is None:
            desc_col = _guess_description_col(
                ncols, {j for j, score in enumerate(date_score) if score} |
                {date_col, debit_col, credit_col, balance_col, amount_col}, body)

        for r in body:
            iso, flags = _statement_date(r[date_col], dayfirst=dayfirst,
                                         default_year=default_year, period=period)
            if not iso:
                if r == rows[0] or re.search(r"\bdate\b", r[date_col], re.I):
                    continue
                if out and desc_col is not None and r[desc_col] and not any(
                        parse_amount(cell) is not None for cell in r):
                    # A description continued on another ruled-table row.
                    if not _SECTION_HEADER_RE.match(r[desc_col]):
                        out[-1].description += " " + " ".join(r[desc_col].split())
                        out[-1].flags = tuple(dict.fromkeys(
                            (*out[-1].flags, "multiline_description")))
                continue
            amount = _row_amount(r, debit_col, credit_col, amount_col)
            if amount is None:
                continue
            balance = parse_amount(r[balance_col]) if balance_col is not None else None
            desc = " ".join(r[desc_col].split()) if desc_col is not None else ""
            if _BALANCE_SEED_RE.match(desc) or re.fullmatch(
                    r"(?:closing|ending|new)\s+balance", desc, re.I):
                continue
            if desc_col is not None and "\n" in r[desc_col]:
                flags += ("multiline_description",)
            category = _card_category(desc, native_amount=amount) if account_type == "card" else ""
            if account_type == "card":
                amount = _card_amount(amount, category)
            out.append(
                Transaction(
                    date=iso,
                    description=desc,
                    amount=amount,
                    balance=balance,
                    currency=currency,
                    flags=flags,
                    category=category,
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
        # An explicitly printed zero adjustment is still a real ledger row.
        if debit is not None or credit is not None:
            return Decimal("0")
    if amount_col is not None:
        return parse_amount(row[amount_col])
    return None


# --------------------------------------------------------------------------- #
# Strategy 2: borderless text lines
# --------------------------------------------------------------------------- #
# Leading date token, then the rest of the line. We grab trailing amounts later.
_LEADING_DATE_RE = re.compile(
    r"^\s*("
    r"\d{1,4}[/\-.]\d{1,2}(?:[/\-.]\d{1,4})?"  # short MM/DD needs year hint
    r"|[A-Za-z]{3,9}\.?\s+\d{1,2}(?:,?\s*\d{4})?"  # Jan 5 / Jan 5, 2024
    r"|\d{1,2}\s+[A-Za-z]{3,9}\.?(?:\s+\d{4})?"  # 5 Jan 2024
    r")\s+(.*\S)\s*$"
)
# A dated balance-seed line carrying a single number states the STARTING balance,
# not a transaction — we use it to seed the running balance. This must be an
# ANCHORED, whole-description match: an unanchored substring test would also fire
# on real transactions that merely mention these words (e.g. "TRANSFER TO OPENING
# SAVINGS BALANCE 200.00"), silently dropping them from the output and poisoning
# the running balance. Covers the common seed labels across US / UK / AU / card
# statements: "opening/beginning/previous/prior balance" and "balance
# brought/carried forward" (and the "balance b/f" shorthand).
_BALANCE_SEED_RE = re.compile(
    r"^(?:"
    r"(?:opening|beginning|previous|prior)\s+balance"
    r"|balance\s+(?:brought|carried)\s+forward"
    r"|balance\s+b\s*/?\s*f"
    r")$",
    re.IGNORECASE,
)
# One amount token (currency/sign/parens aware) used to peel trailing numbers.
_AMOUNT_TOKEN_RE = re.compile(
    r"(?:[$£€¥₩]|R\$|HK\$|US\$)?\s*"
    r"(?:\(|\+|-)?\s*"
    r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+\.\d+"
)
_PAGE_BOUNDARY = "\x00STX_PAGE_BOUNDARY\x00"
_SECTION_HEADER_RE = re.compile(
    r"^(?:page\s+\d+\b|(?:(?:transaction|posting|posted)\s+)?date\b.*\b(?:amount|description)\b|"
    r"(?:statement|account)\s+(?:period|ending|number|statement)\b|"
    r".*\b(?:statement|transaction history)\s*$)", re.IGNORECASE
)
# Parse amounts as complete suffixes, including spaced currency and DR/CR.
_AMOUNT_SUFFIX_RE = re.compile(
    r"(?<!\S)(?:\(\s*)?(?:[+-]\s*)?"
    r"(?:[$£€¥₩]|R\$|HK\$|US\$)?\s*"
    r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s*\))?(?:\s*-)?(?:\s*(?:DR|CR))?\s*$", re.IGNORECASE
)


def _sign_from_delta(
    amount: Decimal, anchor: Optional[Decimal], balance: Optional[Decimal]
) -> Decimal:
    """Sign ``amount`` from a running-balance movement, when it is trustworthy.

    ``anchor`` is the balance this row moved *from*; ``balance`` is the balance it
    moved *to*. A balance that dropped is money out (debit => negative), one that
    rose is money in (credit => positive). The movement is trusted only when its
    magnitude matches this row's amount within a cent — a mismatch means the
    balance chain is broken/stale (an intervening row carried no balance, so the
    delta spans two transactions) and the parsed sign is safer. Re-signing on a
    bogus delta would silently flip an explicitly-signed amount (parens, trailing
    DR, leading minus); when either balance is missing or the magnitudes disagree
    we decline and keep the parsed sign.
    """
    if balance is None or anchor is None:
        return amount
    delta = balance - anchor
    if abs(delta) != abs(amount):
        return amount
    if delta < 0:
        return -abs(amount)
    if delta > 0:
        return abs(amount)
    return amount


@dataclass
class _Row:
    """One parsed borderless line, pre-sign-assignment.

    ``is_seed`` marks a starting-balance line (e.g. "OPENING BALANCE"): it is not
    emitted as a transaction but its ``balance`` anchors the running chain.
    """

    iso: str
    desc: str
    amount: Decimal
    balance: Optional[Decimal]
    is_seed: bool
    flags: tuple[str, ...] = ()
    explicit_sign: bool = False
    category: str = ""


def _parse_rows(
    lines: Sequence[str],
    *,
    dayfirst: bool,
    default_year: Optional[int],
    period: Optional[tuple[str, str]] = None,
    account_type: str = "deposit",
) -> List[_Row]:
    """Parse borderless lines into :class:`_Row` records (no sign inference yet).

    Continuation lines (no leading date, no amount) fold into the previous
    *transaction* row's description, matching the single-pass scanner's memo
    behaviour. Seed lines are kept in sequence so they can anchor the chain from
    either side (a trailing opening balance is the anchor for the oldest row on a
    newest-first statement).
    """
    rows: List[_Row] = []
    last_txn: Optional[_Row] = None
    section = ""
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        if line == _PAGE_BOUNDARY or _SECTION_HEADER_RE.match(line.strip()):
            last_txn = None
            continue
        if account_type == "card":
            for label, category in (("payments_credits", "payment_credit"),
                                    ("purchases", "purchase"), ("fees", "fee"),
                                    ("interest", "interest")):
                if re.fullmatch(r"(?:" + _TOTAL_LABELS[label] + r")(?:\s*\(continued\))?",
                                line.strip(), re.I):
                    section = category
                    last_txn = None
                    break
            else:
                category = None
            if category:
                continue
        m = _LEADING_DATE_RE.match(line)
        if not m:
            # Continuation line: fold into the previous transaction's memo.
            if last_txn is not None and not _AMOUNT_TOKEN_RE.search(line):
                extra = line.strip()
                if extra:
                    last_txn.desc = (last_txn.desc + " " + extra).strip()
                    last_txn.flags = tuple(dict.fromkeys(
                        (*last_txn.flags, "multiline_description")))
            continue

        date_tok, rest = m.group(1), m.group(2)
        # Credit-card detail tables print transaction and posting dates. The
        # posting date is the ledger date; the first date stays out of the memo.
        if account_type == "card":
            posted = _LEADING_DATE_RE.match(rest)
            if posted:
                date_tok, rest = posted.group(1), posted.group(2)
        iso, flags = _statement_date(date_tok, dayfirst=dayfirst,
                                     default_year=default_year, period=period)
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

        # A dated balance-seed line carrying a single number is the starting
        # balance, not a transaction. Matched ANCHORED against the whole stripped
        # description so a real transaction that merely mentions these words
        # (e.g. "TRANSFER TO OPENING SAVINGS BALANCE") is not swallowed.
        if n_strip == 1 and _BALANCE_SEED_RE.match(desc.strip()):
            seed = parse_amount(amount_str)
            if seed is not None:
                rows.append(
                    _Row(iso=iso, desc=desc, amount=seed, balance=seed, is_seed=True)
                )
                continue
        if n_strip == 1 and re.fullmatch(r"(?:closing|ending|new)\s+balance", desc, re.I):
            continue

        amount = parse_amount(amount_str)
        if amount is None:
            continue
        category = _card_category(desc, section, amount) if account_type == "card" else ""
        if account_type == "card":
            amount = _card_amount(amount, category)
        explicit_sign = bool(re.search(r"[()+-]|\b(?:DR|CR)\b", amount_str, re.I))
        row = _Row(iso=iso, desc=desc, amount=amount, balance=balance, is_seed=False,
                   flags=flags, explicit_sign=explicit_sign, category=category)
        rows.append(row)
        last_txn = row
    return rows


def _statement_direction(rows: Sequence[_Row]) -> str:
    """Return ``"descending"``, ``"ascending"`` or ``"mixed"`` for the txn dates.

    Balance-delta inference is direction-sensitive: on an oldest-first statement a
    row's balance is the *previous* row's balance moved by *this* row's amount; on
    a newest-first statement it is the *next* (older) row's balance instead. We
    classify from the transaction rows' ISO dates (which sort lexicographically),
    ignoring seed lines. A run is "descending" when it never increases and drops
    at least once, "ascending" when it never decreases and rises at least once;
    same-date ties are tolerated on both sides (real statements routinely have
    several transactions on one day) so a single tie does not misclassify the
    whole statement. Anything genuinely non-monotonic is "mixed" and handled with
    the conservative oldest-first path.
    """
    isos = [r.iso for r in rows if not r.is_seed]
    if len(isos) < 2:
        return "ascending"
    pairs = list(zip(isos, isos[1:]))
    never_up = all(a >= b for a, b in pairs)
    never_down = all(a <= b for a, b in pairs)
    if never_up and any(a > b for a, b in pairs):
        return "descending"
    if never_down and any(a < b for a, b in pairs):
        return "ascending"
    return "mixed"


def _from_lines(
    lines: Sequence[str],
    *,
    currency: str,
    dayfirst: bool,
    default_year: Optional[int],
    period: Optional[tuple[str, str]] = None,
    account_type: str = "deposit",
    opening_balance: Optional[Decimal] = None,
) -> List[Transaction]:
    rows = _parse_rows(lines, dayfirst=dayfirst, default_year=default_year,
                       period=period, account_type=account_type)
    direction = _statement_direction(rows)

    out: List[Transaction] = []
    if direction == "descending":
        # Newest-first: each row's balance = the balance it moved *from* moved by
        # THIS row's amount, so sign from (balance - anchor), where the anchor is
        # the next (older) balance in the SAME continuous chain. Getting the anchor
        # right is the whole game:
        #
        # * It must be the IMMEDIATELY following record, never the next non-empty
        #   one. Skipping a balance-less row would let the delta span two
        #   transactions and, on a magnitude coincidence, confidently mis-sign the
        #   row (even flip an explicit paren debit). A balance-less neighbour is a
        #   chain break -> no anchor -> decline (keep parsed sign).
        #
        # * A SEED line is a period boundary, not a running balance, so it may
        #   anchor the row above it ONLY when it is the statement's opening balance
        #   at the very tail. A seed sitting BETWEEN transactions (e.g. a
        #   "PREVIOUS BALANCE" from a concatenated newer period) opens a different
        #   period; anchoring the older-period row on it would compare across the
        #   boundary and can confidently flip a real credit to a debit. So a
        #   non-final seed also breaks the chain.
        #
        # Adjacent transaction rows (the equal-magnitude repro) still resolve,
        # because this reads each row's own movement rather than a neighbour's.
        last_idx = len(rows) - 1
        for i, row in enumerate(rows):
            if row.is_seed:
                continue
            nxt = rows[i + 1] if i + 1 < len(rows) else None
            if nxt is None or (nxt.is_seed and i + 1 != last_idx):
                anchor: Optional[Decimal] = None  # chain break: decline
            else:
                anchor = nxt.balance
            amount, flags = _resolve_row_sign(row, anchor, account_type)
            out.append(
                Transaction(
                    date=row.iso,
                    description=row.desc,
                    amount=amount,
                    balance=row.balance,
                    currency=currency,
                    flags=flags,
                    category=row.category,
                )
            )
        return out

    # Oldest-first (or mixed/ambiguous, handled conservatively): sign from the
    # PREVIOUS balance. ``anchor`` is the last balance we trust; ``chain_broken``
    # guards the coincidence where a balance-less row leaves the anchor stale and
    # the next row's spanning delta happens to match |amount| — in that state the
    # next balanced row may only RE-ANCHOR, never re-sign.
    anchor: Optional[Decimal] = opening_balance
    chain_broken = False
    for row in rows:
        if row.is_seed:
            anchor = row.balance
            chain_broken = False
            continue
        if chain_broken:
            amount = row.amount  # do not re-sign across a broken chain
            flags = row.flags
        else:
            amount, flags = _resolve_row_sign(row, anchor, account_type)
        if row.balance is not None:
            anchor = row.balance
            chain_broken = False
        else:
            chain_broken = True
        out.append(
            Transaction(
                date=row.iso,
                description=row.desc,
                amount=amount,
                balance=row.balance,
                currency=currency,
                flags=flags,
                category=row.category,
            )
        )
    return out


def _resolve_row_sign(row: _Row, anchor: Optional[Decimal], account_type: str):
    if row.explicit_sign or account_type == "card":
        return row.amount, row.flags
    amount = _sign_from_delta(row.amount, anchor, row.balance)
    if row.balance is not None and anchor is not None and row.balance != anchor \
            and abs(row.balance - anchor) == abs(row.amount):
        return amount, (*row.flags, "sign_from_balance")
    return amount, row.flags


def _trailing_amounts(rest: str) -> List[str]:
    """Return the run of amount-looking tokens at the END of ``rest``."""
    return [token for _, token in _amount_suffixes(rest)]


def _amount_suffixes(rest: str) -> list[tuple[int, str]]:
    trailing = []
    remaining = rest.rstrip()
    while remaining:
        match = _AMOUNT_SUFFIX_RE.search(remaining)
        if match is None:
            break
        token = match.group().strip()
        if not looks_like_amount(token):
            break
        # A bare integer immediately before a monetary amount is commonly a
        # merchant/reference identifier ("BATCH 42 300.50"), not a balance.
        if trailing and re.fullmatch(r"\d+", token):
            break
        trailing.append((match.start(), token))
        remaining = remaining[:match.start()].rstrip()
    return list(reversed(trailing))


def _strip_trailing_numbers(rest: str, n: int) -> str:
    if n <= 0:
        return rest.strip()
    suffixes = _amount_suffixes(rest)
    if n > len(suffixes):
        return rest.strip()
    return " ".join(rest[:suffixes[-n][0]].split())


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
) -> StatementTransactions:
    """Convert already-extracted statement content into transactions.

    Pass any combination of ``full_text`` (used for year / day-first inference),
    ``lines`` (for the borderless strategy) and ``tables`` (for the ruled-table
    strategy). Ruled tables win when they parse (see :func:`_choose_strategy`),
    otherwise the line scanner is used. Raises :class:`ConversionError` if
    neither finds anything.
    """
    hint_text = "\n".join([full_text, *(lines or []), *(
        " ".join(cell or "" for cell in row)
        for table in (tables or []) for row in table if row)])
    _assert_single_account(hint_text)
    if default_year is None:
        default_year = _infer_year(hint_text)
    if dayfirst is None:
        dayfirst = _infer_dayfirst(hint_text)
    period = _statement_period(hint_text, dayfirst)
    account_type = _account_type(hint_text)
    totals = extract_totals(hint_text, account_type=account_type)
    _assert_transaction_dates(hint_text, dayfirst=dayfirst, default_year=default_year,
                              period=period, account_type=account_type)

    table_txns: List[Transaction] = []
    if tables:
        table_txns = _from_tables(
            tables, currency=currency, dayfirst=dayfirst, default_year=default_year,
            period=period, account_type=account_type,
        )

    line_txns: List[Transaction] = []
    if lines:
        line_txns = _from_lines(
            lines, currency=currency, dayfirst=dayfirst, default_year=default_year,
            period=period, account_type=account_type,
            opening_balance=totals.get("opening"),
        )

    _inherit_table_metadata(table_txns, line_txns, account_type)
    chosen = _choose_strategy(table_txns, line_txns)
    if not chosen and not _proven_no_activity(hint_text, totals, account_type):
        raise ConversionError(
            "No transactions found. The statement may be image-only (needs OCR) "
            "or use an unsupported layout."
        )
    layout = account_type + ("_table" if table_txns and chosen is table_txns else "_lines")
    return StatementTransactions(chosen, reconciliation=reconcile(
        chosen, totals, account_type=account_type), layout=layout)


def _proven_no_activity(text, totals, account_type):
    required = (("previous", "payments_credits", "purchases", "fees", "interest", "new")
                if account_type == "card" else ("opening", "closing"))
    if any(totals.get(key) is None for key in required):
        return False
    flow_keys = (("payments_credits", "purchases", "fees", "interest")
                 if account_type == "card" else ("money_in", "money_out"))
    printed_zero = all(totals.get(key) == 0 for key in flow_keys)
    explicit = bool(re.search(r"\bno\s+(?:account\s+)?(?:activity|transactions)\b", text, re.I))
    return printed_zero or explicit


def _inherit_table_metadata(table_txns, line_txns, account_type):
    """Carry section provenance into the independently extracted ruled cells."""
    candidates = list(line_txns)
    for row in table_txns:
        for index, candidate in enumerate(candidates):
            if row.date == candidate.date and abs(row.amount) == abs(candidate.amount) \
                    and row.description == candidate.description:
                row.flags = tuple(dict.fromkeys((*row.flags, *(flag for flag in candidate.flags
                    if flag != "sign_from_balance"))))
                if account_type == "card":
                    row.category = candidate.category
                    row.amount = candidate.amount
                    row.type = "debit" if row.amount < 0 else "credit"
                candidates.pop(index)
                break


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
) -> StatementTransactions:
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

    from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect
    from pdfminer.pdfparser import PDFSyntaxError
    pdf_errors = (PDFPasswordIncorrect, PDFEncryptionError, PDFSyntaxError)
    try:
        from pdfplumber.utils.exceptions import PdfminerException
    except ImportError:  # Older supported pdfplumber versions raise directly.
        pass
    else:
        pdf_errors += (PdfminerException,)

    all_lines: List[str] = []
    pages = []
    text_parts: List[str] = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                txt = page.extract_text() or ""
                if not txt.strip() and page.images:
                    raise ConversionError(
                        "A PDF page has no extractable text (scanned/image-only). "
                        "Run OCR first; mixed scanned/text PDFs cannot be converted safely."
                    )
                text_parts.append(txt)
                page_lines = txt.splitlines()
                page_tables = page.extract_tables() or []
                pages.append((page_lines, page_tables, bool(page.images)))
                # Prevent page headings/footers becoming transaction memos, but
                # retain the running balance chain across consecutive pages.
                if all_lines:
                    all_lines.append(_PAGE_BOUNDARY)
                all_lines.extend(page_lines)
    except pdf_errors as exc:
        error = exc.args[0] if exc.args and isinstance(exc.args[0], Exception) else exc
        if isinstance(error, (PDFPasswordIncorrect, PDFEncryptionError)):
            raise ConversionError(
                "Password-protected PDF. Unlock it locally and upload an unprotected copy."
            ) from exc
        raise ConversionError("Invalid or damaged PDF. Upload a valid bank-statement PDF.") from exc

    full_text = "\n".join(text_parts)
    if not full_text.strip():
        raise ConversionError(
            "No extractable text in PDF (likely a scanned/image-only file). "
            "Run OCR first; OCR is out of scope for this tool."
        )

    _assert_single_account(full_text)
    if default_year is None:
        default_year = _infer_year(full_text)
    if dayfirst is None:
        dayfirst = _infer_dayfirst(full_text)
    period = _statement_period(full_text, dayfirst)
    account_type = _account_type(full_text)
    totals = extract_totals(full_text, account_type=account_type)
    _assert_transaction_dates(full_text, dayfirst=dayfirst, default_year=default_year,
                              period=period, account_type=account_type)
    line_txns = _from_lines(all_lines, currency=currency, dayfirst=dayfirst,
                            default_year=default_year, period=period,
                            account_type=account_type, opening_balance=totals.get("opening"))
    # Select per page: one ruled page must not hide transactions on a later
    # borderless page. Global line parsing above retains cross-page balance signs.
    chosen = []
    used_tables = False
    offset = 0
    for page_lines, page_tables, has_images in pages:
        row_count = sum(not row.is_seed for row in _parse_rows(
            page_lines, dayfirst=dayfirst, default_year=default_year,
            period=period, account_type=account_type))
        page_line_txns = line_txns[offset:offset + row_count]
        offset += row_count
        table_txns = _from_tables(page_tables, currency=currency, dayfirst=dayfirst,
                                 default_year=default_year, period=period,
                                 account_type=account_type)
        _inherit_table_metadata(table_txns, page_line_txns, account_type)
        page_chosen = _choose_strategy(table_txns, page_line_txns)
        used_tables = used_tables or bool(table_txns and page_chosen is table_txns)
        if has_images and not page_chosen:
            raise ConversionError(
                "An image-bearing PDF page has no readable transactions. It may "
                "contain a scanned body beneath selectable headers. Run OCR first "
                "or upload text-only statement pages; this PDF cannot be converted safely."
            )
        chosen.extend(page_chosen)
    if not chosen and not _proven_no_activity(full_text, totals, account_type):
        raise ConversionError(
            "No transactions found. The statement may be image-only (needs OCR) "
            "or use an unsupported layout."
        )
    return StatementTransactions(chosen, reconciliation=reconcile(
        chosen, totals, account_type=account_type),
        layout=account_type + ("_table" if used_tables else "_lines"))
