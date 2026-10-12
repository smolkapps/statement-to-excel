"""Engine tests against the synthetic PDF fixtures + error paths.

`acmebank` (clean ruled table) is asserted EXACTLY. The two messier layouts are
asserted on the fields that matter (date, amount, balance) with a field-level
accuracy floor, since description merging on borderless text is heuristic.
"""

from decimal import Decimal

import pytest

from statement_to_excel.engine import (
    ConversionError,
    convert_pdf,
    convert_text,
    summarize,
)
from tests.conftest import load_expected


def _key(t):
    return (t.date, t.amount, t.balance)


def test_acmebank_exact(fixtures_dir):
    txns = convert_pdf(fixtures_dir / "acmebank.pdf")
    expected = load_expected("acmebank")
    got = [t.to_dict() for t in txns]
    assert got == expected


def test_columnarcredit_exact(fixtures_dir):
    txns = convert_pdf(fixtures_dir / "columnarcredit.pdf")
    expected = load_expected("columnarcredit")
    got = [t.to_dict() for t in txns]
    assert got == expected


def test_minimalchecking_field_accuracy(fixtures_dir):
    txns = convert_pdf(fixtures_dir / "minimalchecking.pdf")
    expected = [
        (e["date"], Decimal(e["amount"]), Decimal(e["balance"]))
        for e in load_expected("minimalchecking")
    ]
    got = {_key(t) for t in txns}
    matched = sum(1 for e in expected if e in got)
    assert matched / len(expected) >= 0.85, (matched, len(expected), got)
    # description continuation should be folded for the GROCERY OUTLET row
    grocery = [t for t in txns if t.date == "2024-03-07"]
    assert grocery and "produce dept" in grocery[0].description


def test_minimalchecking_balance_delta_signs(fixtures_dir):
    """Borderless rows (no debit/credit column) get their sign from the running
    balance: a drop is a debit, a rise a credit — even though the amount token
    is written unsigned. Regression guard for the naive "everything is a credit"
    bug."""
    txns = convert_pdf(fixtures_dir / "minimalchecking.pdf")
    by_date = {t.date: t for t in txns}

    # GROCERY OUTLET drops 3600.00 -> 3541.60, so it must be a debit.
    grocery = by_date["2024-03-07"]
    assert grocery.amount == Decimal("-58.40")
    assert grocery.type == "debit"
    # ATM WITHDRAWAL and the utility autopay likewise decrease the balance.
    assert by_date["2024-03-14"].type == "debit"
    assert by_date["2024-03-22"].amount == Decimal("-200.00")
    # DIRECT DEPOSIT and INTEREST raise the balance -> credits.
    assert by_date["2024-03-03"].type == "credit"
    assert by_date["2024-03-03"].amount == Decimal("2100.00")
    assert by_date["2024-03-29"].type == "credit"

    # The dated single-number "OPENING BALANCE" line seeds the running balance
    # rather than becoming a phantom +1500 credit, so the FULL unfiltered
    # summarize() totals reconcile with the real cashflow — no date whitelist.
    assert "2024-03-01" not in by_date
    assert len(txns) == 5
    s = summarize(txns)
    assert s.total_credit == Decimal("2101.25")  # 2100.00 + 1.25
    assert s.total_debit == Decimal("378.40")  # 58.40 + 120.00 + 200.00
    assert s.net == Decimal("1722.85")


def test_balance_delta_infers_debit_on_borderless_line():
    """A single balance-decreasing borderless row is typed a debit, not the
    naive credit the unsigned amount token would otherwise produce."""
    txns = convert_text(
        lines=[
            "01/05/2024 OPENING DEPOSIT 500.00 500.00",
            "01/09/2024 HARDWARE STORE 30.00 470.00",
        ],
    )
    hardware = next(t for t in txns if t.date == "2024-01-09")
    assert hardware.amount == Decimal("-30.00")
    assert hardware.type == "debit"
    s = summarize(txns)
    assert s.total_debit == Decimal("30.00")
    assert s.total_credit == Decimal("500.00")
    assert s.net == Decimal("470.00")


def test_stale_balance_chain_keeps_explicit_sign():
    """A balance-less row leaves prev_balance stale, so the next row's delta
    spans two transactions and no longer matches that row's amount. The
    magnitude guard then declines to re-sign and the explicitly-parsed sign
    (parentheses => debit) survives instead of being flipped by the bogus
    delta direction."""
    txns = convert_text(
        lines=[
            "01/05/2024 OPENING DEPOSIT 500.00 500.00",
            "01/07/2024 MOBILE REFUND 20.00",  # no balance -> prev_balance stays 500
            "01/09/2024 CARD PURCHASE (5.00) 515.00",  # explicit debit
        ],
    )
    purchase = next(t for t in txns if t.date == "2024-01-09")
    # delta = 515 - 500 = +15 (spans the balance-less refund), which does NOT
    # match |amount| = 5, so the naive override that would flip this to +5.00
    # credit is declined and the parsed -5.00 debit is kept.
    assert purchase.amount == Decimal("-5.00")
    assert purchase.type == "debit"


def test_newest_first_statement_declines_to_resign():
    """On a reverse-chronological (newest-first) statement the delta between
    adjacent rows reflects a *neighbouring* row's amount, not the current one,
    so it won't match this row's magnitude. The guard declines rather than
    flipping a deposit into a bogus debit."""
    txns = convert_text(
        lines=[
            "03/10/2024 SECOND DEPOSIT 50.00 1050.00",
            "03/05/2024 FIRST DEPOSIT 900.00 1000.00",
        ],
    )
    first = next(t for t in txns if t.date == "2024-03-05")
    # delta = 1000 - 1050 = -50 would naively flip this to -900.00 debit; but
    # |delta| = 50 != |amount| = 900, so the parsed +900.00 credit is kept.
    assert first.amount == Decimal("900.00")
    assert first.type == "credit"


def test_scanned_pdf_raises(fixtures_dir):
    with pytest.raises(ConversionError):
        convert_pdf(fixtures_dir / "scanned_empty.pdf")


def test_convert_text_empty_raises():
    with pytest.raises(ConversionError):
        convert_text(full_text="nothing here", lines=["just words"], tables=[])


def test_summarize():
    txns = convert_text(
        lines=[
            "01/05/2024 PAYDAY 1000.00 1000.00",
            "01/06/2024 COFFEE -4.50 995.50",
        ],
    )
    s = summarize(txns)
    assert s.count == 2
    assert s.total_credit == Decimal("1000.00")
    assert s.total_debit == Decimal("4.50")
    assert s.net == Decimal("995.50")
    assert s.start_date == "2024-01-05"
    assert s.end_date == "2024-01-06"


def test_dayfirst_inference_from_unambiguous_date():
    # 25/12/2024 forces day-first; the other rows then parse day-first too.
    txns = convert_text(
        lines=[
            "25/12/2024 GIFT SHOP 50.00 450.00",
            "02/01/2024 NEW YEAR 10.00 440.00",
        ],
    )
    dates = sorted(t.date for t in txns)
    assert dates == ["2024-01-02", "2024-12-25"]


def test_table_strategy_beats_lines_when_both_present():
    # A ruled table with 3 rows should win over a single stray line.
    tables = [
        [
            ["Date", "Description", "Amount", "Balance"],
            ["01/01/2024", "A", "10.00", "10.00"],
            ["01/02/2024", "B", "-5.00", "5.00"],
            ["01/03/2024", "C", "20.00", "25.00"],
        ]
    ]
    lines = ["01/09/2024 STRAY 1.00 1.00"]
    txns = convert_text(tables=tables, lines=lines, full_text="2024")
    assert len(txns) == 3
    assert txns[0].description == "A"


# --------------------------------------------------------------------------- #
# Adversarial regression guards: residual sign-inference / data-loss holes
# --------------------------------------------------------------------------- #
def test_newest_first_adjacent_equal_magnitude_debits_not_flipped():
    """HOLE 1. A newest-first (descending-date) statement with two ADJACENT,
    EQUAL-magnitude debits defeats the old forward-delta guard: the forward
    delta between the two rows equals |amount| but reflects the NEIGHBOUR's
    movement, so the override mis-signs both real debits as credits. The fix
    detects descending order and signs each row from its own movement — this
    row's balance minus the NEXT (older) row's balance — so equal magnitudes on
    adjacent rows no longer collide and both real debits are recovered."""
    txns = convert_text(
        lines=[
            "03/10/2024 CARD PURCHASE 50.00 950.00",
            "03/08/2024 CARD PURCHASE 50.00 1000.00",
            "03/05/2024 OPENING BALANCE 1050.00",
        ],
    )
    by_date = {t.date: t for t in txns}
    # Newest-first: each row's balance = the NEXT (older) row's balance moved by
    # THIS row's amount. 03/10 = 950-1000 = -50 debit; 03/08 = 1000-1050 = -50
    # debit. Under forward-delta both equal-magnitude debits were flipped to +50
    # credits; the descending-aware inference recovers the real debits.
    assert by_date["2024-03-10"].amount == Decimal("-50.00")
    assert by_date["2024-03-10"].type == "debit"
    assert by_date["2024-03-08"].amount == Decimal("-50.00")
    assert by_date["2024-03-08"].type == "debit"
    # The opening-balance line seeds the chain rather than becoming a phantom row.
    assert "2024-03-05" not in by_date
    assert len(txns) == 2
    s = summarize(txns)
    assert s.total_debit == Decimal("100.00")
    assert s.total_credit == Decimal("0.00")


def test_chain_broken_coincidental_delta_keeps_explicit_paren_debit():
    """HOLE 2. After a balance-less row the chain is broken; the engine already
    emits a balance=None row (it KNOWS the chain broke). It must NOT then use
    the next balanced row to RE-SIGN: here the stale delta (505-500 = +5)
    coincidentally equals |amount| = 5 and would flip an EXPLICIT paren debit
    (5.00) into a +5 credit. The next balanced row may only re-anchor
    prev_balance, never re-sign."""
    txns = convert_text(
        lines=[
            "01/05/2024 OPENING DEPOSIT 500.00 500.00",
            "01/07/2024 MOBILE REFUND 10.00",  # no balance -> chain breaks
            "01/09/2024 CARD PURCHASE (5.00) 505.00",  # explicit paren debit
        ],
    )
    purchase = next(t for t in txns if t.date == "2024-01-09")
    assert purchase.amount == Decimal("-5.00")
    assert purchase.type == "debit"


def test_unanchored_balance_seed_does_not_swallow_real_transaction():
    """HOLE 3. _BALANCE_SEED_RE was an unanchored substring match, so a dated
    SINGLE-number row whose description merely CONTAINS 'opening ... balance' /
    'beginning ... balance' (e.g. a transfer INTO an opening-balance savings
    account) was silently DROPPED from output AND poisoned prev_balance (it set
    the running balance to that transfer amount, mis-signing later rows). The
    seed pattern must match only a bare literal seed line, not real
    transactions. This uses a single trailing number so it hits the n_strip==1
    seed branch — the exact path the unanchored regex corrupted."""
    txns = convert_text(
        lines=[
            "01/05/2024 OPENING DEPOSIT 500.00 500.00",
            "01/07/2024 TRANSFER TO OPENING SAVINGS BALANCE 200.00",
            "01/09/2024 CARD PURCHASE 30.00 470.00",
        ],
    )
    by_date = {t.date: t for t in txns}
    # The transfer is a real transaction and must SURVIVE (not be swallowed as a
    # balance seed) — it is NOT a bare "OPENING BALANCE" seed line. Pre-fix the
    # unanchored regex dropped it, emitting only 2 rows.
    assert "2024-01-07" in by_date, [t.description for t in txns]
    assert len(txns) == 3, [t.description for t in txns]
    assert by_date["2024-01-07"].description == "TRANSFER TO OPENING SAVINGS BALANCE"
    # It must NOT have poisoned prev_balance to 200. Pre-fix the swallowed seed
    # set prev_balance=200, so the 01/09 delta was 470-200=+270 (mismatch) and the
    # row stayed a naive +30 for the WRONG reason. Here we prove the seed did not
    # hijack the chain: with the real (balance-less) transfer breaking the chain,
    # the 01/09 row is emitted from its own parsed amount, not a 470-vs-200 delta.
    purchase = by_date["2024-01-09"]
    assert purchase.balance == Decimal("470.00")
    assert abs(purchase.amount) == Decimal("30.00")


def test_descending_gap_does_not_confidently_missign_a_credit():
    """HOLE 1 (regression on the fix itself). On a newest-first statement the
    per-row anchor must be the IMMEDIATELY following record's balance, not the
    next non-empty one. A balance-less row in the middle must break the chain, or
    a delta spanning two transactions can coincidentally match |amount| and
    confidently flip a sign. Here the 03/10 REFUND is a real +100 credit
    (1100 -> 1200); the balance-less 03/09 PURCHASE sits between it and the next
    balance (1300), and 1200-1300 = -100 == |amount| would wrongly type it a
    debit. The gap must make the engine DECLINE and keep the (naive positive)
    credit instead of confidently mis-signing it."""
    txns = convert_text(
        lines=[
            "03/10/2024 REFUND 100.00 1200.00",
            "03/09/2024 PURCHASE 200.00",  # balance-less -> chain gap
            "03/08/2024 DEPOSIT 300.00 1300.00",
            "03/05/2024 OPENING BALANCE 1000.00",
        ],
    )
    by_date = {t.date: t for t in txns}
    refund = by_date["2024-03-10"]
    # It must NOT be a confident debit. The truthful sign is credit (+100); the
    # non-negotiable property is that it is not flipped negative by a bogus
    # two-transaction delta.
    assert refund.amount == Decimal("100.00"), refund
    assert refund.type != "debit"


def test_descending_gap_does_not_flip_explicit_paren_debit():
    """HOLE 2 x HOLE 1. The descending path must honour the chain_broken
    principle too: an EXPLICIT parenthesised debit must never be re-signed across
    a balance-less gap. 03/10 CARD PURCHASE (5.00) is an explicit debit; the
    balance-less 03/09 refund breaks the chain, and the spanning delta
    1205-1200 = +5 == |amount| would otherwise flip it to a +5 credit. The parsed
    -5.00 debit must survive."""
    txns = convert_text(
        lines=[
            "03/10/2024 CARD PURCHASE (5.00) 1205.00",
            "03/09/2024 MOBILE REFUND 10.00",  # balance-less -> chain gap
            "03/08/2024 DEPOSIT 200.00 1200.00",
            "03/05/2024 OPENING BALANCE 1000.00",
        ],
    )
    by_date = {t.date: t for t in txns}
    purchase = by_date["2024-03-10"]
    assert purchase.amount == Decimal("-5.00"), purchase
    assert purchase.type == "debit"


def test_descending_midsequence_seed_is_not_a_false_anchor():
    """HOLE 1 (regression on the fix itself, second variant). On a newest-first
    statement a SEED line (e.g. a "PREVIOUS BALANCE" from a concatenated newer
    statement period) can sit BETWEEN transactions. A seed is a period-opening
    balance, not a running balance, so it must NOT anchor the row above it unless
    it is the statement's opening balance at the very tail — otherwise the
    older-period row is compared across the period boundary and a real credit is
    confidently flipped to a debit. Here 03/20 REFUND is a real +200 credit, but
    the mid-sequence PREVIOUS BALANCE 1400.00 would give delta 1200-1400 = -200 ==
    |amount|, flipping it to a -200 debit. The boundary must break the chain so
    the refund is not mis-signed as a debit."""
    txns = convert_text(
        lines=[
            "03/20/2024 REFUND 200.00 1200.00",  # real credit
            "03/15/2024 PREVIOUS BALANCE 1400.00",  # mid-sequence seed / boundary
            "03/10/2024 OLD TXN 40.00 1360.00",
            "03/05/2024 OPENING BALANCE 1400.00",
        ],
    )
    by_date = {t.date: t for t in txns}
    refund = by_date["2024-03-20"]
    # The non-negotiable property: a real credit is not confidently flipped to a
    # debit by a cross-boundary delta. The seed lines are not emitted as rows.
    assert refund.type != "debit", refund
    assert refund.amount == Decimal("200.00"), refund
    assert "2024-03-15" not in by_date  # PREVIOUS BALANCE seed, not a txn
    assert "2024-03-05" not in by_date  # OPENING BALANCE seed, not a txn


def test_brought_forward_and_previous_balance_seed_the_chain():
    """HOLE 4. Scope gap: 'BALANCE BROUGHT FORWARD' and 'PREVIOUS BALANCE'
    (standard on UK / AU / card statements) are starting-balance seeds too. They
    must seed the running balance (not become a phantom credit row), so the
    following row's sign is inferred and the totals reconcile."""
    for seed_desc in ("BALANCE BROUGHT FORWARD", "PREVIOUS BALANCE"):
        txns = convert_text(
            lines=[
                f"01/05/2024 {seed_desc} 500.00",
                "01/09/2024 CARD PURCHASE 30.00 470.00",
            ],
        )
        by_date = {t.date: t for t in txns}
        assert "2024-01-05" not in by_date, (seed_desc, [t.description for t in txns])
        assert len(txns) == 1, (seed_desc, [t.description for t in txns])
        purchase = by_date["2024-01-09"]
        assert purchase.amount == Decimal("-30.00"), seed_desc
        assert purchase.type == "debit", seed_desc
        s = summarize(txns)
        assert s.total_debit == Decimal("30.00"), seed_desc
        assert s.total_credit == Decimal("0.00"), seed_desc
