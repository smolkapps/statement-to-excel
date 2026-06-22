"""The normalized :class:`Transaction` model and (de)serialization helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

__all__ = ["Transaction"]


@dataclass
class Transaction:
    """A single normalized statement line.

    Attributes
    ----------
    date:
        ISO ``YYYY-MM-DD`` string.
    description:
        Free-text merchant / memo; multi-line descriptions are merged upstream.
    amount:
        Signed :class:`~decimal.Decimal`. **Negative means a debit** (money out).
    balance:
        Optional running balance after this transaction.
    currency:
        ISO-ish currency code, defaults to ``"USD"``.
    type:
        ``"debit"`` or ``"credit"``, derived from the sign of ``amount`` when not
        supplied explicitly.
    """

    date: str
    description: str
    amount: Decimal
    balance: Optional[Decimal] = None
    currency: str = "USD"
    type: str = field(default="")

    def __post_init__(self) -> None:
        if self.amount is not None and not isinstance(self.amount, Decimal):
            self.amount = Decimal(str(self.amount))
        if self.balance is not None and not isinstance(self.balance, Decimal):
            self.balance = Decimal(str(self.balance))
        self.description = (self.description or "").strip()
        if not self.type:
            self.type = (
                "debit" if self.amount is not None and self.amount < 0 else "credit"
            )

    # -- serialization ----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Plain-dict form with Decimals stringified for stable JSON output."""
        return {
            "date": self.date,
            "description": self.description,
            "amount": _dec_str(self.amount),
            "balance": _dec_str(self.balance) if self.balance is not None else None,
            "currency": self.currency,
            "type": self.type,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Transaction":
        """Inverse of :meth:`to_dict`; tolerates missing optional keys."""
        bal = d.get("balance")
        return cls(
            date=d["date"],
            description=d["description"],
            amount=Decimal(str(d["amount"])),
            balance=Decimal(str(bal)) if bal is not None else None,
            currency=d.get("currency", "USD"),
            type=d.get("type", ""),
        )


def _dec_str(value: Decimal) -> str:
    """Render a Decimal as a plain (non-exponential) string, e.g. '-1234.56'."""
    # Normalize -0 to 0 and avoid scientific notation.
    if value == 0:
        value = Decimal("0")
    return f"{value:f}"
