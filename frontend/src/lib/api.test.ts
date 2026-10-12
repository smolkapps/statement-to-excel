import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  apiUrl,
  base64ToBlob,
  buildConvertForm,
  convertStatement,
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

  it("omits the preview flag and returns no blob for fmt=json", async () => {
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
    expect(out.blob).toBeNull();
    expect(out.result.summary.count).toBe(1);
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
