"""Exact statement checks, independent of PDF extraction and output writers.

Only supplied printed figures are evidence. Deposit cashflow totals are optional;
both endpoint balances are required. Cards require all six printed summary terms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping, Sequence

from .transaction import Transaction

ZERO = Decimal("0")
DEPOSIT_KEYS = ("opening", "money_in", "money_out", "closing")
CARD_KEYS = ("previous", "payments_credits", "purchases", "fees", "interest", "new")


@dataclass
class Reconciliation:
    status: str
    account_type: str
    terms: dict[str, Decimal | None]
    printed_totals: dict[str, Decimal | None]
    difference: Decimal | None
    row_flags: list[dict] = field(default_factory=list)
    check_differences: dict[str, Decimal] = field(default_factory=dict)

    def to_dict(self) -> dict:
        def money(values):
            return {key: f"{value:f}" if value is not None else None
                    for key, value in values.items()}
        return {
            "status": self.status,
            "account_type": self.account_type,
            "terms": money(self.terms),
            "printed_totals": money(self.printed_totals),
            "difference": f"{self.difference:f}" if self.difference is not None else None,
            "row_flags": self.row_flags,
            "check_differences": money(self.check_differences),
        }


def reconcile(
    rows: Sequence[Transaction],
    extracted_totals: Mapping[str, Decimal | None],
    *,
    account_type: str = "deposit",
) -> Reconciliation:
    """Check parsed rows against independently printed statement figures.

    ``difference`` is calculated closing/new minus printed closing/new. Additional
    subtotal and running-balance differences prevent cancelling errors from being
    labelled balanced. No rounding, tolerances, I/O or inferred printed zeros.
    """
    keys = CARD_KEYS if account_type == "card" else DEPOSIT_KEYS
    printed = {key: extracted_totals.get(key) for key in keys}
    if any(value is not None and not isinstance(value, Decimal)
           for value in printed.values()):
        raise TypeError("Printed totals must be Decimal values or None")
    flags = [{"row_index": index, "flags": list(row.flags)}
             for index, row in enumerate(rows) if row.flags]
    if account_type == "card":
        categories = {"payment_credit": "payments_credits", "purchase": "purchases",
                      "fee": "fees", "interest": "interest"}
        terms = {key: ZERO for key in keys}
        terms["previous"] = printed["previous"]
        terms["new"] = printed["new"]
        for row in rows:
            category = (row.category if row.category in categories else
                        "payment_credit" if row.amount > 0 else "purchase")
            key = categories.get(category)
            if key is not None:
                terms[key] += row.amount if key == "payments_credits" else -row.amount
        required = keys
        opening_key, closing_key = "previous", "new"
    else:
        terms = {
            "opening": printed["opening"],
            "money_in": sum((row.amount for row in rows if row.amount > 0), ZERO),
            "money_out": sum((-row.amount for row in rows if row.amount < 0), ZERO),
            "closing": printed["closing"],
        }
        required = ("opening", "closing")
        opening_key, closing_key = "opening", "closing"
    if any(printed[key] is None for key in required):
        return Reconciliation("cannot_check", account_type, terms, printed, None, flags)

    if account_type == "card":
        calculated = (terms["previous"] - terms["payments_credits"] + terms["purchases"]
                      + terms["fees"] + terms["interest"])
    else:
        calculated = terms["opening"] + terms["money_in"] - terms["money_out"]
    difference = calculated - printed[closing_key]
    checks = {closing_key: difference}
    for key in keys:
        if key not in (opening_key, closing_key) and printed[key] is not None:
            checks[key] = terms[key] - printed[key]

    # Validate every printed row balance against the complete parsed ledger.
    # Most recent first deposits retain their output order but check oldest first.
    ordered = sorted(enumerate(rows), key=lambda item: item[1].date)
    if len(rows) > 1 and all(a.date >= b.date for a, b in zip(rows, rows[1:])) \
            and any(a.date > b.date for a, b in zip(rows, rows[1:])):
        ordered = list(reversed(list(enumerate(rows))))
    running = printed[opening_key]
    for index, row in ordered:
        running += -row.amount if account_type == "card" else row.amount
        if row.balance is not None:
            checks[f"row_balance_{index}"] = running - row.balance
    status = "balanced" if all(value == ZERO for value in checks.values()) else "not_balanced"
    return Reconciliation(status, account_type, terms, printed, difference, flags, checks)
