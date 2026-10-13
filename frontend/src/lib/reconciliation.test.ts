import { describe, expect, it } from "vitest";
import type { Reconciliation } from "./api";
import { formatStatementMoney, reconciliationDifference, reconciliationStatus } from "./reconciliation";

function checked(): Reconciliation {
  return {
    status: "balanced", account_type: "deposit", difference: "0.00", row_flags: [],
    terms: { opening: "100.00", money_in: "50.00", money_out: "20.00", closing: "130.00" },
    printed_totals: { opening: "100.00", money_in: null, money_out: null, closing: "130.00" },
  };
}

describe("reconciliation presentation evidence", () => {
  it("accepts checked deposit totals with optional printed flow totals", () => {
    expect(reconciliationStatus(checked())).toBe("balanced");
  });

  it.each([undefined, { ...checked(), terms: {} }, { ...checked(), printed_totals: {} },
    { ...checked(), difference: "NaN" }, { ...checked(), account_type: "unknown" },
    { ...checked(), terms: { ...checked().terms, money_in: "60.00" } },
    { ...checked(), printed_totals: { ...checked().printed_totals, money_in: "60.00" } },
    { ...checked(), check_differences: { money_out: "-5.00" } },
    { ...checked(), check_differences: { money_out: "private-description" } },
  ])("does not show balanced without complete, consistent printed evidence: %s", (value) => {
    expect(reconciliationStatus(value as Reconciliation | undefined)).toBe("cannot_check");
  });

  it("uses a signed subtotal discrepancy when the closing discrepancy is zero", () => {
    const value = { ...checked(), status: "not_balanced" as const, check_differences: { money_in: "0.00", money_out: "-4.25" } };
    expect(reconciliationStatus(value)).toBe("not_balanced");
    expect(reconciliationDifference(value)).toBe("-4.25");
  });

  it("does not claim a mismatch without a valid discrepancy", () => {
    expect(reconciliationStatus({ ...checked(), status: "not_balanced" })).toBe("cannot_check");
  });
});

describe("statement money formatting", () => {
  it.each([
    ["1000000.01", "$1,000,000.01"],
    ["9007199254740993.01", "$9,007,199,254,740,993.01"],
    ["-0.01", "-$0.01"], ["1", "$1.00"], ["0.001", "$0.001"],
  ])("preserves exact decimal digits for %s", (value, expected) => {
    expect(formatStatementMoney(value, "USD", "en")).toBe(expected);
  });
});
