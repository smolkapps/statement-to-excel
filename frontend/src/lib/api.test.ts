import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  apiUrl,
  base64ToBlob,
  buildConvertForm,
  convertStatement,
  fetchAccount,
  fetchCheckoutAvailability,
  fetchCheckoutStatus,
  openCheckout,
  type OutputFormat,
} from "./api";

// jsdom's Blob has no .text(); read via FileReader (what browsers also support).
const readBlobText = (b: Blob) =>
  new Promise<string>((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(r.error);
    r.readAsText(b);
  });

describe("api helpers", () => {
  it("builds a same-origin URL by default", () => {
    expect(apiUrl("/api/convert")).toBe("/api/convert");
  });

  it("builds the multipart form with all metering fields", () => {
    const blob = new Blob(["%PDF-1.4"], { type: "application/pdf" });
    const form = buildConvertForm(blob, {
      accountId: "web_abc",
      fmt: "csv",
      currency: "EUR",
    });
    expect(form.get("account_id")).toBe("web_abc");
    expect(form.get("fmt")).toBe("csv");
    expect(form.get("currency")).toBe("EUR");
    expect(form.get("file")).toBeInstanceOf(Blob);
  });

  it("omits account identity from an unmetered conversion form", () => {
    const form = buildConvertForm(new Blob(["synthetic"]), { fmt: "xlsx", currency: "USD" });
    expect(form.get("account_id")).toBeNull();
    expect(form.get("fmt")).toBe("xlsx");
  });

  it("decodes base64 into a typed Blob", async () => {
    const blob = base64ToBlob(btoa("PKdata"), "application/zip");
    expect(blob.type).toBe("application/zip");
    expect(await readBlobText(blob)).toBe("PKdata");
  });
});

describe("convertStatement", () => {
  const pdf = new Blob(["%PDF-1.4"], { type: "application/pdf" });
  const summary = {
    count: 1,
    total_debit: "0",
    total_credit: "5.00",
    net: "5.00",
    currency: "USD",
    start_date: "2024-01-05",
    end_date: "2024-01-05",
  };
  const rows = [
    {
      date: "2024-01-05",
      description: "DEPOSIT",
      amount: "5.00",
      balance: null,
      currency: "USD",
      type: "credit",
    },
  ];
  const charge = { pages: 2, from_included: 2, from_credits: 0, credits_after: 0 };

  const fakeResponse = (status: number, body: unknown) =>
    ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    }) as Response;

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("makes exactly ONE metered request for a binary format", async () => {
    const fetchMock = vi.fn(async () =>
      fakeResponse(200, {
        transactions: rows,
        summary,
        charge,
        file_b64: btoa("PK-fake-xlsx"),
        filename: "statement.xlsx",
        media_type: "application/vnd.test",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const out = await convertStatement(pdf, {
      accountId: "web_abc",
      fmt: "xlsx",
      currency: "USD",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const form = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
    expect((form.body as FormData).get("preview")).toBe("1"); // rows + file, one charge
    expect(out.result.transactions).toHaveLength(1);
    expect(out.result.charge?.pages).toBe(2);
    expect(out.filename).toBe("statement.xlsx");
    expect(await readBlobText(out.blob!)).toBe("PK-fake-xlsx");
    expect(out.blob!.type).toBe("application/vnd.test");
  });

  it("omits the preview flag and returns a downloadable JSON blob", async () => {
    const fetchMock = vi.fn(async () =>
      fakeResponse(200, { transactions: rows, summary, charge }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const out = await convertStatement(pdf, {
      accountId: "web_abc",
      fmt: "json",
      currency: "USD",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
    expect((init.body as FormData).get("preview")).toBeNull();
    expect(out.blob?.type).toBe("application/json");
    expect(JSON.parse(await readBlobText(out.blob!)).transactions).toEqual(rows);
    expect(out.result.summary.count).toBe(1);
  });

  it("coalesces overlapping conversion calls and sends a stable retry key", async () => {
    let complete!: (value: Response) => void;
    const fetchMock = vi.fn(() => new Promise<Response>((resolve) => { complete = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["%PDF-1.4"], "duplicate.pdf");
    const opts = { accountId: "retry_account", fmt: "json" as const, currency: "USD" };
    const first = convertStatement(file, opts);
    const duplicate = convertStatement(file, opts);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    complete(fakeResponse(200, { transactions: rows, summary, charge }));
    await Promise.all([first, duplicate]);
    const firstHeaders = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
    const retry = convertStatement(file, opts);
    complete(fakeResponse(200, { transactions: rows, summary, charge }));
    await retry;
    const retryHeaders = (fetchMock.mock.calls[1] as unknown[])[1] as RequestInit;
    expect(firstHeaders.headers).toEqual(retryHeaders.headers);
    expect((firstHeaders.headers as Record<string, string>)["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("keeps the conversion idempotency key after a lost network response", async () => {
    const file = new File(["synthetic"], "retry.pdf");
    const opts = { accountId: "lost_response", fmt: "json" as const, currency: "USD" };
    const fetchMock = vi.fn().mockRejectedValueOnce(new TypeError("Network error"))
      .mockResolvedValueOnce(fakeResponse(200, { transactions: rows, summary, charge }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(convertStatement(file, opts)).rejects.toThrow("Network error");
    await convertStatement(file, opts);
    expect((fetchMock.mock.calls[0][1] as RequestInit).headers)
      .toEqual((fetchMock.mock.calls[1][1] as RequestInit).headers);
  });

  it.each<OutputFormat>(["xlsx", "csv", "json"])("preserves a %s timeout status and reuses the same key for retry", async (fmt) => {
    const file = new File(["synthetic"], "retry.pdf");
    const opts = { accountId: "timeout_retry", fmt, currency: "USD" };
    const detail = "Conversion took too long. Please try again with a smaller statement or split it into fewer pages.";
    const fetchMock = vi.fn().mockResolvedValueOnce(fakeResponse(504, { detail }))
      .mockResolvedValueOnce(fakeResponse(200, {
        transactions: rows, summary, charge,
        ...(fmt === "json" ? {} : { file_b64: btoa("converted-output") }),
      }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(convertStatement(file, opts)).rejects.toMatchObject({
      name: "ApiError", kind: "parse", status: 504, message: detail,
    });
    const retried = await convertStatement(file, opts);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect((fetchMock.mock.calls[0][1] as RequestInit).headers)
      .toEqual((fetchMock.mock.calls[1][1] as RequestInit).headers);
    expect(retried.result.transactions).toEqual(rows);
    expect(retried.blob).toBeInstanceOf(Blob);
  });

  it("fetches authoritative account state and sends checkout intents to Stripe configuration", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(fakeResponse(200, { plan: "free", pro: false }))
      .mockResolvedValueOnce(fakeResponse(200, { session_id: "cs_test_1", checkout_url: "https://checkout.stripe.com/c/pay/cs_test_1", mode: "test", provider: "stripe" }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await fetchAccount("web_test")).toMatchObject({ plan: "free", pro: false });
    await openCheckout("web_test", "starter", "00000000-0000-4000-8000-000000000001");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/account/web_test");
    const init = fetchMock.mock.calls[1][1] as RequestInit;
    expect(init.headers).toEqual({ "Content-Type": "application/json", "Idempotency-Key": "00000000-0000-4000-8000-000000000001" });
    expect(JSON.parse(init.body as string)).toEqual({ account_id: "web_test", sku: "starter" });
  });

  it.each(["javascript:alert(1)", "https://malicious.example/payment"])("refuses an unexpected checkout URL: %s", async (url) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse(200, { checkout_url: url })));
    await expect(openCheckout("web_test", "starter", "test-key")).rejects.toThrow("invalid Stripe URL");
  });

  it("rejects a metered binary response whose downloadable output is missing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse(200, { transactions: rows, summary, charge })));
    await expect(convertStatement(new Blob(["synthetic"]), { accountId: "missing_output", fmt: "xlsx", currency: "USD" }))
      .rejects.toMatchObject({ kind: "parse", message: expect.stringContaining("output is missing") });
  });

  it("checks session status through the authenticated account capability", async () => {
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse(200, { session_id: "cs_test_1", sku: "pack_50", status: "fulfilled" }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await fetchCheckoutStatus("web_test", "cs_test_1")).toMatchObject({ status: "fulfilled" });
    expect(fetchMock).toHaveBeenCalledWith("/api/checkout/cs_test_1?account_id=web_test");
  });

  it.each([
    [true, true],
    [false, false],
    [undefined, false],
    ["true", false],
    [1, false],
  ])("enables checkout only for strict pricing availability %s", async (value, expected) => {
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse(200, { checkout_available: value }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await fetchCheckoutAvailability()).toBe(expected);
    expect(fetchMock).toHaveBeenCalledWith("/api/pricing");
  });

  it("rejects failed availability requests so the App can fail closed", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse(503, { detail: "internal configuration" })));
    await expect(fetchCheckoutAvailability()).rejects.toThrow();
  });

  it("maps 402 to an 'insufficient' ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => fakeResponse(402, { detail: "no credits" })),
    );
    await expect(
      convertStatement(pdf, { accountId: "a", fmt: "csv", currency: "USD" }),
    ).rejects.toMatchObject({ name: "ApiError", kind: "insufficient" });
  });

  it("preserves the HTTP status so billing conflicts can receive localized UI errors", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => fakeResponse(409, { detail: "Idempotency key belongs to another conversion." })));
    await expect(convertStatement(new Blob(["synthetic"]), { accountId: "conflict", fmt: "json", currency: "USD" }))
      .rejects.toMatchObject({ name: "ApiError", kind: "parse", status: 409 });
  });

  it("maps a parse failure (422) to a 'parse' ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => fakeResponse(422, { detail: "image-only PDF" })),
    );
    const err = await convertStatement(pdf, {
      accountId: "a",
      fmt: "csv",
      currency: "USD",
    }).catch((e) => e as ApiError);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).kind).toBe("parse");
  });
});
