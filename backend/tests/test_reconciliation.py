"""Adversarial checks against independently printed statement figures."""

from decimal import Decimal as D

import pytest

from statement_to_excel.engine import ConversionError, convert_text, extract_totals
from statement_to_excel.reconciliation import reconcile
from statement_to_excel.transaction import Transaction


def row(amount, balance=None, *, date="2024-01-02", category="", flags=()):
    return Transaction(date, "Synthetic transaction", D(amount),
                       D(balance) if balance is not None else None,
                       category=category, flags=flags)


def deposit(**overrides):
    values = {"opening": D("100.00"), "money_in": D("25.00"),
              "money_out": D("10.00"), "closing": D("115.00")}
    values.update(overrides)
    return values


def card(**overrides):
    values = {"previous": D("100.00"), "payments_credits": D("50.00"),
              "purchases": D("25.00"), "fees": D("2.00"),
              "interest": D("1.00"), "new": D("78.00")}
    values.update(overrides)
    return values


def test_exact_deposit_and_optional_printed_cashflow_totals():
    rows = [row("25", "125"), row("-10", "115")]
    checked = reconcile(rows, deposit())
    assert checked.status == "balanced"
    assert checked.difference == D("0")
    assert checked.to_dict()["terms"]["money_out"] == "10"
    assert reconcile(rows, {"opening": D("100"), "closing": D("115")}).status == "balanced"


@pytest.mark.parametrize("rows", [
    [row("25", "125")],  # missing debit
    [row("25", "125"), row("-10", "115"), row("-3", "112")],  # extra
    [row("25", "125"), row("-11", "114")],  # wrong amount
    [row("25", "125"), row("10", "115")],  # flipped sign
])
def test_incomplete_or_wrong_deposit_rows_never_balance(rows):
    assert reconcile(rows, deposit()).status == "not_balanced"


def test_exact_decimal_has_no_one_cent_tolerance():
    result = reconcile([row("25"), row("-10.001")], deposit())
    assert result.status == "not_balanced"
    assert result.difference == D("-0.001")


def test_cancelling_cashflow_errors_fail_printed_subtotals():
    result = reconcile([row("30"), row("-15")], deposit())
    assert result.status == "not_balanced"
    assert result.difference == 0
    assert result.check_differences["money_in"] == 5
    assert result.check_differences["money_out"] == 5


def test_wrong_running_balance_fails_even_if_final_equation_matches():
    result = reconcile([row("25", "124"), row("-10", "115")], deposit())
    assert result.status == "not_balanced"
    assert result.check_differences["row_balance_0"] == 1


def test_printed_endpoints_are_required_and_are_never_inferred():
    result = reconcile([row("25", "125"), row("-10", "115")], {})
    assert result.status == "cannot_check"
    assert result.difference is None
    assert result.printed_totals == dict.fromkeys(("opening", "money_in", "money_out", "closing"))


def test_card_equation_uses_categories_and_requires_every_printed_component():
    rows = [row("50", "50", category="payment_credit"),
            row("-25", "75", category="purchase"),
            row("-2", "77", category="fee"), row("-1", "78", category="interest")]
    assert reconcile(rows, card(), account_type="card").status == "balanced"
    assert reconcile(rows, card(interest=None), account_type="card").status == "cannot_check"
    result = reconcile(rows[:-1], card(), account_type="card")
    assert result.status == "not_balanced"
    assert result.difference == -1


def test_unknown_card_category_cannot_hide_an_extra_row():
    totals = card(previous=D("100"), new=D("100"), payments_credits=D("0"),
                  purchases=D("0"), fees=D("0"), interest=D("0"))
    assert reconcile([row("50", category="unknown")], totals,
                     account_type="card").status == "not_balanced"


def test_flags_have_original_zero_based_row_indices():
    rows = [row("25", flags=("multiline_description",)), row("-10")]
    assert reconcile(rows, deposit()).to_dict()["row_flags"] == [
        {"row_index": 0, "flags": ["multiline_description"]}]
    assert set(rows[0].to_dict()) == {"date", "description", "amount", "balance", "currency", "type"}


def test_december_january_year_inference_and_description_provenance():
    result = convert_text(lines=[
        "Statement period December 20, 2023 - January 19, 2024",
        "Opening balance 100.00", "Money in 25.00", "Money out 10.00", "Closing balance 115.00",
        "12/28 PAYDAY 25.00 125.00", "payroll continuation",
        "01/03 GROCERY 10.00 115.00",
    ])
    assert [r.date for r in result] == ["2023-12-28", "2024-01-03"]
    assert set(result[0].flags) == {"year_inferred_rollover", "sign_from_balance", "multiline_description"}
    assert result[1].amount == -10
    assert result.reconciliation.status == "balanced"
    assert result.layout == "deposit_lines"


def test_explicit_sign_survives_inconsistent_balance_and_is_not_flagged_as_inferred():
    result = convert_text(lines=["Opening balance 100.00", "Closing balance 90.00",
                                 "01/02/2024 PURCHASE -10.00 110.00"])
    assert result[0].amount == -10
    assert "sign_from_balance" not in result[0].flags
    assert result.reconciliation.status == "not_balanced"


def test_card_posting_dates_sections_minus_payment_and_independent_totals():
    result = convert_text(lines=[
        "Credit Card Statement period 01/01/2024 - 01/31/2024",
        "Previous balance 100.00", "Payments and credits -50.00", "Purchases 25.00",
        "Fees charged 2.00", "Interest charged 1.00", "New balance 78.00",
        "Payments and Credits", "Transaction Date Posting Date Description Amount Balance",
        "01/01 01/02 AUTOPAY THANK YOU -50.00 50.00", "Purchases",
        "01/03 01/04 SYNTHETIC STORE 25.00 75.00", "Fees",
        "01/05 01/06 ANNUAL FEE 2.00 77.00", "Interest",
        "01/07 01/08 INTEREST CHARGED 1.00 78.00",
    ])
    assert [r.date for r in result] == ["2024-01-02", "2024-01-04", "2024-01-06", "2024-01-08"]
    assert [r.amount for r in result] == [50, -25, -2, -1]
    assert [r.category for r in result] == ["payment_credit", "purchase", "fee", "interest"]
    assert result.reconciliation.status == "balanced"


def test_card_neutral_memo_negative_payment_without_section():
    result = convert_text(lines=["Previous balance 100.00", "New balance 50.00",
                                 "01/01/2024 01/02/2024 AUTOPAY THANK YOU -50.00"])
    assert result[0].category == "payment_credit"
    assert result[0].amount == 50
    assert result.reconciliation.status == "cannot_check"


def test_no_activity_requires_independent_evidence():
    with pytest.raises(ConversionError):
        convert_text(lines=["Opening balance 100.00", "Closing balance 100.00"])
    result = convert_text(lines=["Opening balance 100.00", "Money in 0.00",
                                 "Money out 0.00", "Closing balance 100.00"])
    assert result == []
    assert result.reconciliation.status == "balanced"
    with pytest.raises(ConversionError):
        convert_text(lines=["No activity", "Opening balance 100.00"])


def test_totals_do_not_swallow_transaction_descriptions_or_conflicting_summaries():
    assert extract_totals("01/02/2024 TRANSFER TO OPENING BALANCE 50.00")["opening"] is None
    assert extract_totals("Opening balance 100.00\nOpening balance 200.00")["opening"] is None
    assert extract_totals("Purchases -40.00", account_type="card")["purchases"] == -40


def test_large_amount_and_overdraft_are_exact():
    result = convert_text(lines=["Opening balance -25.00", "Money in 1,000,000.01",
        "Money out 0.00", "Closing balance 999,975.01",
        "01/02/2024 DEPOSIT 1,000,000.01 999,975.01"])
    assert result[0].amount == D("1000000.01")
    assert result.reconciliation.status == "balanced"


@pytest.mark.parametrize("period", ["December 20 - January 19, 2024", "12/20 - 01/19/2024"])
def test_rollover_period_printing_year_only_once(period):
    result = convert_text(lines=[f"Statement period {period}",
        "Opening balance 100.00", "Money in 20.00", "Money out 10.00", "Closing balance 110.00",
        "12/28 PAYDAY 20.00 120.00", "01/02 STORE 10.00 110.00"])
    assert [r.date for r in result] == ["2023-12-28", "2024-01-02"]
    assert all("year_inferred_rollover" in r.flags for r in result)
    assert result.reconciliation.status == "balanced"


def test_dated_deposit_and_fee_rows_never_become_printed_subtotals():
    totals = extract_totals("Opening balance 100.00\nClosing balance 120.00\n"
                            "01/01/2024 Deposit 20.00 120.00")
    assert totals["money_in"] is None
    assert extract_totals("Fees charged 5.00\n01/02/2024 Fee 5.00 105.00",
                          account_type="card")["fees"] == 5
    assert extract_totals("Deposits to account 20.00")["money_in"] is None


def test_card_separately_printed_payments_and_other_credits_are_added():
    totals = extract_totals("Payments -40.00\nOther credits -10.00", account_type="card")
    assert totals["payments_credits"] == 50
    totals = extract_totals("Payments and credits -50.00\nOther credits -10.00", account_type="card")
    assert totals["payments_credits"] == 50  # no double counting aggregate summary


def test_short_dates_use_two_digit_years_from_printed_period():
    result = convert_text(lines=["Statement period 12/20/23 - 01/19/24",
        "Opening balance 100.00", "Money in 20.00", "Money out 10.00", "Closing balance 110.00",
        "12/28 PAYDAY 20.00 120.00", "01/02 STORE 10.00 110.00"])
    assert [r.date for r in result] == ["2023-12-28", "2024-01-02"]
    assert result.reconciliation.status == "balanced"


@pytest.mark.parametrize("incoming,outgoing", [
    ("Deposits and other credits", "Withdrawals and other debits"),
    ("Deposits/Additions", "Withdrawals/Subtractions"),
    ("Deposits & Credits", "Withdrawals & Deductions"),
])
def test_common_deposit_summary_labels(incoming, outgoing):
    totals = extract_totals(f"{incoming} 25.00\n{outgoing} 10.00")
    assert totals["money_in"] == 25
    assert totals["money_out"] == 10


def test_printed_period_year_is_not_overridden_by_four_digit_balances():
    result = convert_text(lines=["Statement period January 1 - January 31, 2024",
        "Opening balance 2000.00", "Money in 10.00", "Money out 10.00", "Closing balance 2000.00",
        "Jan 2 DEPOSIT 10.00 2010.00", "Jan 3 PURCHASE 10.00 2000.00"])
    assert [r.date for r in result] == ["2024-01-02", "2024-01-03"]
    assert result.reconciliation.status == "balanced"


def test_impossible_transaction_date_cannot_disappear_into_balanced_zero_activity():
    with pytest.raises(ConversionError, match="transaction date"):
        convert_text(lines=["Statement period 02/01/2024 - 02/29/2024",
            "Opening balance 100.00", "Money in 0.00", "Money out 0.00", "Closing balance 100.00",
            "02/30/2024 INVALID DATE 0.00"])


def test_explicit_card_heading_preserves_card_semantics_without_summary_totals():
    result = convert_text(lines=["Synthetic Credit Card Statement", "Statement year 2024",
                                 "01/01 01/02 AUTOPAY THANK YOU -50.00",
                                 "01/03 01/04 SYNTHETIC SHOP 25.00"])
    assert [r.amount for r in result] == [50, -25]
    assert result.reconciliation.status == "cannot_check"
    assert result.reconciliation.account_type == "card"
    assert result.layout == "card_lines"
