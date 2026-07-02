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
export interface ChargeInfo {
  pages: number;
  from_included: number;
  from_credits: number;
  credits_after: number;
}

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

async function throwApiError(res: Response): Promise<never> {
  const body = await res.json().catch(() => ({}) as { detail?: string });
  if (res.status === 402) {
    throw new ApiError("insufficient", body.detail ?? "insufficient credits");
  }
  throw new ApiError("parse", body.detail ?? `request failed (${res.status})`);
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
  /** The downloadable file for binary formats; null when fmt is "json". */
  blob: Blob | null;
  filename: string;
}

/**
 * Convert a statement with ONE metered request: the response carries the rows
 * for the preview table and, for binary formats (`preview` flag), the file
 * itself base64-inline — so the account is charged once per conversion, not
 * once for the preview plus once for the download.
 */
export async function convertStatement(
  file: File | Blob,
  opts: { accountId: string; fmt: OutputFormat; currency: string },
): Promise<ConvertOutcome> {
  const form = buildConvertForm(file, opts);
  if (opts.fmt !== "json") form.append("preview", "1");
  const res = await fetch(apiUrl("/api/convert"), { method: "POST", body: form });
  if (!res.ok) await throwApiError(res);
  const body = (await res.json()) as ConvertPreviewResponse;
  const blob = body.file_b64
    ? base64ToBlob(body.file_b64, body.media_type ?? "application/octet-stream")
    : null;
  return {
    result: body,
    blob,
    filename: body.filename ?? `statement.${opts.fmt}`,
  };
}
