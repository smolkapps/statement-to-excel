// Thin client for the FastAPI backend. The base URL is configurable via the
// Vite env var VITE_API_BASE (defaults to "" => same-origin / dev proxy).

export const API_BASE: string =
  (import.meta.env?.VITE_API_BASE as string | undefined) ?? "";

export interface TransactionRow {
  date: string;
  description: string;
  amount: string;
  balance: string | null;
  currency: string;
  type: string;
}

export interface Summary {
  count: number;
  total_debit: string;
  total_credit: string;
  net: string;
  currency: string;
  start_date: string | null;
  end_date: string | null;
}

/** The ledger entry the backend returns for a successful metered conversion. */
export interface MeteredChargeInfo {
  metered?: true;
  pages: number;
  from_included: number;
  from_credits: number;
  credits_after: number;
}

export interface UnmeteredChargeInfo {
  metered: false;
  pages: number;
}

export type ChargeInfo = MeteredChargeInfo | UnmeteredChargeInfo;

export interface ConvertJsonResult {
  transactions: TransactionRow[];
  summary: Summary;
  charge?: ChargeInfo;
}

export type OutputFormat = "xlsx" | "csv" | "json";

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

/** Build the multipart form for /api/convert (extracted for unit testing). */
export function buildConvertForm(
  file: File | Blob,
  opts: { accountId?: string; fmt: OutputFormat; currency: string },
): FormData {
  const form = new FormData();
  form.append("file", file);
  if (opts.accountId) form.append("account_id", opts.accountId);
  form.append("fmt", opts.fmt);
  form.append("currency", opts.currency);
  return form;
}

export interface InsufficientError {
  kind: "insufficient";
  detail: string;
}
export interface ParseError {
  kind: "parse";
  detail: string;
}
export type ConvertError = InsufficientError | ParseError;

export class ApiError extends Error {
  constructor(
    public readonly kind: ConvertError["kind"],
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function throwApiError(res: Response): Promise<never> {
  const body = await res.json().catch(() => ({})) as { detail?: unknown };
  const detail = typeof body.detail === "string" ? body.detail : `request failed (${res.status})`;
  if (res.status === 402) {
    throw new ApiError("insufficient", detail, res.status);
  }
  throw new ApiError("parse", detail, res.status);
}

/** Decode a base64 payload into a Blob (for the inline preview download). */
export function base64ToBlob(b64: string, mediaType: string): Blob {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: mediaType });
}

interface ConvertPreviewResponse extends ConvertJsonResult {
  file_b64?: string;
  filename?: string;
  media_type?: string;
}

export interface ConvertOutcome {
  result: ConvertJsonResult;
  /** Downloadable output, including JSON. */
  blob: Blob | null;
  filename: string;
}

/**
 * Convert a statement with ONE metered request: the response carries the rows
 * for the preview table and, for binary formats (`preview` flag), the file
 * itself base64-inline — so the account is charged once per conversion, not
 * once for the preview plus once for the download.
 */
async function requestConversion(
  file: File | Blob,
  opts: { accountId?: string; fmt: OutputFormat; currency: string },
  requestId: string,
): Promise<ConvertOutcome> {
  const form = buildConvertForm(file, opts);
  if (opts.fmt !== "json") form.append("preview", "1");
  const res = await fetch(apiUrl("/api/convert"), {
    method: "POST",
    body: form,
    headers: { "Idempotency-Key": requestId },
  });
  if (!res.ok) await throwApiError(res);
  const body = (await res.json()) as ConvertPreviewResponse;
  if (!Array.isArray(body.transactions) || typeof body.summary?.count !== "number") {
    throw new ApiError("parse", "Conversion service returned an unexpected response. Please try again.");
  }
  if (opts.fmt !== "json" && (typeof body.file_b64 !== "string" || !body.file_b64)) {
    throw new ApiError("parse", "Conversion output is missing. Retry this file to download it without another charge.");
  }
  const blob = body.file_b64
    ? base64ToBlob(body.file_b64, body.media_type ?? "application/octet-stream")
    : opts.fmt === "json"
      ? new Blob([JSON.stringify(body, null, 2)], { type: "application/json" })
      : null;
  return {
    result: body,
    blob,
    filename: body.filename ?? `statement.${opts.fmt}`,
  };
}


// Keep only identity/Promise metadata in a WeakMap. Two clicks share one
// in-flight request; a network retry of this file/options keeps the same key.
// The server independently enforces idempotency without retaining PDF data.
const conversions = new WeakMap<File | Blob, Map<string, {
  requestId: string;
  pending?: Promise<ConvertOutcome>;
}>>();

export function convertStatement(
  file: File | Blob,
  opts: { accountId?: string; fmt: OutputFormat; currency: string },
): Promise<ConvertOutcome> {
  let requests = conversions.get(file);
  if (!requests) {
    requests = new Map();
    conversions.set(file, requests);
  }
  const identity = JSON.stringify([opts.accountId, opts.fmt, opts.currency]);
  let request = requests.get(identity);
  if (!request) {
    request = { requestId: crypto.randomUUID() };
    requests.set(identity, request);
  }
  if (!request.pending) {
    const current = request;
    current.pending = requestConversion(file, opts, current.requestId).finally(() => {
      current.pending = undefined;
    });
  }
  return request.pending!;
}

export interface ServerAccount {
  id: string;
  plan: string;
  credits: number;
  included_pages: number;
  pages_used_this_cycle: number;
  included_remaining: number;
  pro: boolean;
}

export interface CheckoutSession {
  session_id: string;
  checkout_url: string;
  provider: "stripe";
  mode: "test";
}

export async function fetchAccount(accountId: string): Promise<ServerAccount> {
  const response = await fetch(apiUrl(`/api/account/${encodeURIComponent(accountId)}`));
  if (!response.ok) await throwApiError(response);
  return response.json() as Promise<ServerAccount>;
}

export async function openCheckout(
  accountId: string,
  sku: string,
  requestId: string,
): Promise<CheckoutSession> {
  const response = await fetch(apiUrl("/api/checkout"), {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": requestId },
    body: JSON.stringify({ account_id: accountId, sku }),
  });
  if (!response.ok) await throwApiError(response);
  const session = await response.json() as CheckoutSession;
  const url = new URL(session.checkout_url);
  if (url.protocol !== "https:" || url.hostname !== "checkout.stripe.com") {
    throw new Error("Checkout returned an invalid Stripe URL");
  }
  return session;
}

export function navigateCheckout(url: string): void {
  window.location.assign(url);
}


export interface CheckoutStatus {
  session_id: string;
  sku: string;
  status: "pending" | "fulfilled" | "expired" | "cancelled";
}

export async function fetchCheckoutStatus(accountId: string, sessionId: string): Promise<CheckoutStatus> {
  const response = await fetch(apiUrl(`/api/checkout/${encodeURIComponent(sessionId)}?account_id=${encodeURIComponent(accountId)}`));
  if (!response.ok) await throwApiError(response);
  return response.json() as Promise<CheckoutStatus>;
}


/** Billing stays hidden unless the backend explicitly advertises availability. */
export async function fetchCheckoutAvailability(): Promise<boolean> {
  const response = await fetch(apiUrl("/api/pricing"));
  if (!response.ok) await throwApiError(response);
  const pricing = await response.json() as { checkout_available?: unknown };
  return pricing.checkout_available === true;
}
