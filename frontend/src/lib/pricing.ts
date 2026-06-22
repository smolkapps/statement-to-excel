// Pricing catalog + client-side metering math. This mirrors the backend
// `billing.py` model so the UI can show an accurate cost quote *before* hitting
// the API. A parity test asserts this JSON matches the backend catalog.

import pricingData from "../pricing.json";

export interface Plan {
  id: string;
  name: string;
  monthly_price_usd: string;
  included_pages: number;
  overage_per_page_usd: string;
}

export interface CreditPack {
  id: string;
  name: string;
  credits: number;
  price_usd: string;
  per_credit_usd: string;
}

export interface Pricing {
  plans: Plan[];
  credit_packs: CreditPack[];
}

export const PRICING: Pricing = pricingData as Pricing;

export function getPlan(id: string): Plan | undefined {
  return PRICING.plans.find((p) => p.id === id);
}

export function getPack(id: string): CreditPack | undefined {
  return PRICING.credit_packs.find((c) => c.id === id);
}

export interface AccountState {
  planId: string;
  credits: number;
  pagesUsedThisCycle: number;
}

export function newAccount(planId = "free"): AccountState {
  return { planId, credits: 0, pagesUsedThisCycle: 0 };
}

export function includedRemaining(acct: AccountState): number {
  const plan = getPlan(acct.planId) ?? getPlan("free")!;
  return Math.max(0, plan.included_pages - acct.pagesUsedThisCycle);
}

export interface Quote {
  pages: number;
  fromIncluded: number;
  fromCredits: number;
  creditsAfter: number;
  sufficient: boolean;
}

/** How a charge of `pages` would be covered, without applying it. */
export function quote(acct: AccountState, pages: number): Quote {
  const incl = includedRemaining(acct);
  const fromIncluded = Math.min(pages, incl);
  const fromCredits = Math.max(0, pages - fromIncluded);
  return {
    pages,
    fromIncluded,
    fromCredits,
    creditsAfter: acct.credits - fromCredits,
    sufficient: fromCredits <= acct.credits,
  };
}

export function canProcess(acct: AccountState, pages: number): boolean {
  return quote(acct, pages).sufficient;
}

/** Apply a charge, returning a new account state. Throws if insufficient. */
export function charge(acct: AccountState, pages: number): AccountState {
  const q = quote(acct, pages);
  if (!q.sufficient) {
    throw new Error(`Insufficient credits: need ${q.fromCredits}, have ${acct.credits}`);
  }
  return {
    planId: acct.planId,
    credits: acct.credits - q.fromCredits,
    pagesUsedThisCycle: acct.pagesUsedThisCycle + q.fromIncluded,
  };
}

export function addCredits(acct: AccountState, credits: number): AccountState {
  if (credits < 0) throw new Error("credits must be >= 0");
  return { ...acct, credits: acct.credits + credits };
}

export function setPlan(acct: AccountState, planId: string): AccountState {
  if (!getPlan(planId)) throw new Error(`unknown plan: ${planId}`);
  return { ...acct, planId };
}

/** Format a USD amount string like "29" or "0.6000" for display ($29, $0.60). */
export function formatUsd(value: string | number): string {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return String(value);
  // Drop trailing zeros beyond cents but always show cents for non-integers.
  const rounded = Math.round(n * 100) / 100;
  return Number.isInteger(rounded)
    ? `$${rounded}`
    : `$${rounded.toFixed(2)}`;
}
