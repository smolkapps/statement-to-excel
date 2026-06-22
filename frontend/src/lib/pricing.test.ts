import { describe, expect, it } from "vitest";
import {
  addCredits,
  canProcess,
  charge,
  formatUsd,
  getPack,
  getPlan,
  includedRemaining,
  newAccount,
  PRICING,
  quote,
  setPlan,
} from "./pricing";

describe("catalog", () => {
  it("has the four plans and three packs", () => {
    expect(PRICING.plans.map((p) => p.id)).toEqual([
      "free",
      "starter",
      "business",
      "firm",
    ]);
    expect(PRICING.credit_packs.map((c) => c.id)).toEqual([
      "pack_50",
      "pack_200",
      "pack_1000",
    ]);
  });

  it("prices packs at business tier (>= $30) with volume discount", () => {
    const p50 = getPack("pack_50")!;
    expect(Number(p50.price_usd)).toBe(30);
    expect(Number(getPack("pack_1000")!.per_credit_usd)).toBeLessThan(
      Number(p50.per_credit_usd),
    );
  });
});

describe("metering math", () => {
  it("free plan includes 3 pages then runs out", () => {
    let a = newAccount();
    expect(includedRemaining(a)).toBe(3);
    a = charge(a, 3);
    expect(includedRemaining(a)).toBe(0);
    expect(canProcess(a, 1)).toBe(false);
  });

  it("credits cover overage beyond included pages", () => {
    let a = addCredits(newAccount(), 5);
    expect(canProcess(a, 8)).toBe(true);
    expect(canProcess(a, 9)).toBe(false);
    const q = quote(a, 8);
    expect(q.fromIncluded).toBe(3);
    expect(q.fromCredits).toBe(5);
    a = charge(a, 8);
    expect(a.credits).toBe(0);
  });

  it("quote does not mutate the account", () => {
    const a = addCredits(newAccount(), 2);
    const before = { ...a };
    quote(a, 4);
    expect(a).toEqual(before);
  });

  it("charge throws when insufficient and leaves caller's state intact", () => {
    const a = addCredits(newAccount(), 1);
    expect(() => charge(a, 10)).toThrow(/insufficient/i);
    expect(a.credits).toBe(1);
    expect(a.pagesUsedThisCycle).toBe(0);
  });

  it("plan upgrade grants more included pages", () => {
    const a = setPlan(newAccount(), "business");
    expect(getPlan(a.planId)!.included_pages).toBe(500);
    expect(includedRemaining(a)).toBe(500);
  });

  it("rejects an unknown plan", () => {
    expect(() => setPlan(newAccount(), "platinum")).toThrow();
  });
});

describe("formatUsd", () => {
  it("renders integers without cents and decimals with two places", () => {
    expect(formatUsd("29")).toBe("$29");
    expect(formatUsd("0.6000")).toBe("$0.60");
    expect(formatUsd(0.5)).toBe("$0.50");
    expect(formatUsd("199")).toBe("$199");
  });
});
