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

export interface ConvertJsonResult {
  transactions: TransactionRow[];
  summary: Summary;
}

export type OutputFormat = "xlsx" | "csv" | "json";

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

/** Build the multipart form for /api/convert (extracted for unit testing). */
export function buildConvertForm(
  file: File | Blob,
  opts: { accountId: string; fmt: OutputFormat; currency: string },
): FormData {
  const form = new FormData();
  form.append("file", file);
  form.append("account_id", opts.accountId);
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
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Convert and get inline JSON (used to render the preview table). */
export async function convertToJson(
  file: File | Blob,
  opts: { accountId: string; currency: string },
): Promise<ConvertJsonResult> {
  const form = buildConvertForm(file, { ...opts, fmt: "json" });
  const res = await fetch(apiUrl("/api/convert"), { method: "POST", body: form });
  if (res.status === 402) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError("insufficient", body.detail ?? "insufficient credits");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError("parse", body.detail ?? `request failed (${res.status})`);
  }
  return (await res.json()) as ConvertJsonResult;
}

/** Convert and get a downloadable Blob (xlsx/csv). */
export async function convertToBlob(
  file: File | Blob,
  opts: { accountId: string; fmt: "xlsx" | "csv"; currency: string },
): Promise<Blob> {
  const form = buildConvertForm(file, opts);
  const res = await fetch(apiUrl("/api/convert"), { method: "POST", body: form });
  if (res.status === 402) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError("insufficient", body.detail ?? "insufficient credits");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError("parse", body.detail ?? `request failed (${res.status})`);
  }
  return await res.blob();
}

export async function getPricing(): Promise<unknown> {
  const res = await fetch(apiUrl("/api/pricing"));
  return res.json();
}
