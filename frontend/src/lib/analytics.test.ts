import { afterEach, describe, expect, it, vi } from "vitest";
import { track, type AnalyticsEvent } from "./analytics";

describe("analytics privacy boundary", () => {
  afterEach(() => { delete window.umami; });

  it("copies only the two allowlisted conversion properties", () => {
    const analytics = vi.fn();
    window.umami = { track: analytics };
    const metadata = {
      balanced: "no" as const, layout: "card_table" as const, amount: "123.45", date: "2024-01-01",
      name: "Private Name", description: "Private purchase", filename: "private.pdf", account_id: "private-id",
    };
    track("convert-success", metadata);
    expect(analytics.mock.calls).toEqual([["convert-success", { balanced: "no", layout: "card_table" }]]);
  });

  it("replaces arbitrary property values with unknown", () => {
    const analytics = vi.fn();
    window.umami = { track: analytics };
    // @ts-expect-error Invalid values are forbidden at compile time and normalized at runtime.
    track("convert-success", { balanced: "private-amount", layout: "private-filename.pdf" });
    expect(analytics.mock.calls).toEqual([["convert-success", { balanced: "unknown", layout: "unknown" }]]);
  });

  it("keeps other existing events property-free and rejects arbitrary event names", () => {
    const analytics = vi.fn();
    window.umami = { track: analytics };
    track("convert-error");
    // A stale or untyped caller cannot introduce a document-derived event.
    track("private-filename.pdf" as Exclude<AnalyticsEvent, "convert-success">);
    expect(analytics.mock.calls).toEqual([["convert-error"]]);
  });

  it("does not interrupt conversion if analytics fails", () => {
    window.umami = { track: () => { throw new Error("unavailable"); } };
    expect(() => track("convert-success", { balanced: "yes", layout: "deposit_lines" })).not.toThrow();
  });
});
