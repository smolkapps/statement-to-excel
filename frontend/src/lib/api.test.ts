import { describe, expect, it } from "vitest";
import { apiUrl, buildConvertForm } from "./api";

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
});
