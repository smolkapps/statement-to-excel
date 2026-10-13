import type { LocaleCode } from "../i18n";
import type { Reconciliation, ReconciliationStatus, ReconciliationTerm } from "./api";

const DEPOSIT_TERMS: ReconciliationTerm[] = ["opening", "money_in", "money_out", "closing"];
const CARD_TERMS: ReconciliationTerm[] = ["previous", "payments_credits", "purchases", "fees", "interest", "new"];

function decimal(value: unknown): value is string {
  return typeof value === "string" && /^-?\d+(?:\.\d{1,20})?$/.test(value);
}

function nonzero(value: unknown): value is string {
  return decimal(value) && /[1-9]/.test(value);
}

function exact(value: string): bigint {
  const [integer, fraction = ""] = value.replace(/^-/, "").split(".");
  const units = BigInt(integer) * 10n ** 20n + BigInt(fraction.padEnd(20, "0"));
  return value.startsWith("-") ? -units : units;
}

/** A subtotal mismatch can survive even when two errors cancel at closing. */
export function reconciliationDifference(value: Reconciliation): string | null {
  if (nonzero(value.difference)) return value.difference;
  if (value.check_differences && typeof value.check_differences === "object") {
    return Object.values(value.check_differences).find(nonzero) ?? null;
  }
  return null;
}

/** Fail closed for old or incomplete API responses; the engine owns the check. */
export function reconciliationStatus(value: Reconciliation | undefined): ReconciliationStatus {
  if (!value || !["balanced", "not_balanced"].includes(value.status)) return "cannot_check";
  const terms = value.account_type === "deposit" ? DEPOSIT_TERMS
    : value.account_type === "card" ? CARD_TERMS : null;
  const printed = value.account_type === "deposit" ? ["opening", "closing"] as const : CARD_TERMS;
  if (!terms || !value.terms || !value.printed_totals
    || !terms.every((key) => decimal(value.terms[key]))
    || !printed.every((key) => decimal(value.printed_totals[key]))) return "cannot_check";
  if (value.status === "not_balanced") {
    return reconciliationDifference(value) === null ? "cannot_check" : "not_balanced";
  }
  if (!decimal(value.difference) || nonzero(value.difference)
    || (value.check_differences && Object.values(value.check_differences)
      .some((difference) => difference !== null && (!decimal(difference) || nonzero(difference))))) return "cannot_check";
  // Never display a successful equation from internally contradictory terms.
  const term = (key: ReconciliationTerm) => exact(value.terms[key]!);
  const computed = value.account_type === "deposit" ? term("opening") + term("money_in") - term("money_out")
    : term("previous") - term("payments_credits") + term("purchases") + term("fees") + term("interest");
  const closing = value.account_type === "deposit" ? "closing" : "new";
  if (computed !== term(closing) || !terms.every((key) => {
    const amount = value.printed_totals[key];
    return amount === null || amount === undefined || (decimal(amount) && exact(amount) === term(key));
  })) return "cannot_check";
  return "balanced";
}

/** Format exact decimal strings without rounding their integer part to Number. */
export function formatStatementMoney(value: string, currency: string, locale: LocaleCode): string {
  const [integer, fraction = ""] = value.split(".");
  const precision = Math.max(2, fraction.length);
  const whole = BigInt(integer);
  const amount = value.startsWith("-") && whole === 0n ? -0 : whole;
  const formatter = new Intl.NumberFormat(locale, {
    style: "currency", currency, minimumFractionDigits: precision, maximumFractionDigits: precision,
  });
  return formatter.formatToParts(amount)
    .map((part) => part.type === "fraction" ? fraction.padEnd(precision, "0") : part.value).join("");
}
