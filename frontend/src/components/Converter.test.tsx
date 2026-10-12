import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { I18nProvider } from "../i18n/I18nContext";

// Mock the API client so the component test drives the UI, not the network.
// Keep ApiError real (the component branches on `instanceof ApiError`).
const { convertStatement } = vi.hoisted(() => ({ convertStatement: vi.fn() }));
vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return { ...actual, convertStatement };
});

// Import after vi.mock so the component picks up the mocked module.
import { Converter } from "./Converter";
import { ApiError, type ConvertOutcome } from "../lib/api";

function renderConverter(props: Parameters<typeof Converter>[0]) {
  return render(
    <I18nProvider initialLocale="en">
      <Converter {...props} />
    </I18nProvider>,
  );
}

const outcome = (pages: number): ConvertOutcome => ({
  result: {
    transactions: [
      {
        date: "2024-01-05",
        description: "ACH PAYROLL DEPOSIT",
        amount: "3250.00",
        balance: "5250.00",
        currency: "USD",
        type: "credit",
      },
    ],
    summary: {
      count: 1,
      total_debit: "0",
      total_credit: "3250.00",
      net: "3250.00",
      currency: "USD",
      start_date: "2024-01-05",
      end_date: "2024-01-05",
    },
    charge: { pages, from_included: pages, from_credits: 0, credits_after: 0 },
  },
  // A binary format returns a downloadable blob; stub URL below so the
  // component's triggerDownload is a no-op in jsdom.
  blob: new Blob(["PK-fake"], { type: "application/vnd.test" }),
  filename: "statement.xlsx",
});

function selectFileAndConvert() {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
  const file = new File(["%PDF-1.4"], "statement.pdf", {
    type: "application/pdf",
  });
  fireEvent.change(input, { target: { files: [file] } });
  fireEvent.click(screen.getByRole("button", { name: "Convert" }));
  return file;
}

describe("Converter", () => {
  beforeEach(() => {
    convertStatement.mockReset();
    // jsdom has no object-URL support; the download path calls these.
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:mock"),
      revokeObjectURL: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("converts with a SINGLE metered call and renders the preview rows", async () => {
    convertStatement.mockResolvedValue(outcome(3));
    renderConverter({ accountId: "web_test" });

    const file = selectFileAndConvert();

    await waitFor(() =>
      expect(screen.getByText("ACH PAYROLL DEPOSIT")).toBeInTheDocument(),
    );

    // One conversion == exactly one metered request (no separate preview call).
    expect(convertStatement).toHaveBeenCalledTimes(1);
    expect(convertStatement).toHaveBeenCalledWith(file, {
      accountId: "web_test",
      fmt: "xlsx",
      currency: "USD",
    });
    // The summary strip reflects the returned rows.
    expect(screen.getByText("Transactions")).toBeInTheDocument();
  });

  it("mirrors the server charge to onCharged using the returned page count", async () => {
    convertStatement.mockResolvedValue(outcome(4));
    const onCharged = vi.fn();
    renderConverter({ accountId: "web_test", onCharged });

    selectFileAndConvert();

    await waitFor(() => expect(onCharged).toHaveBeenCalled());
    // Mirrors charge.pages (4), not a hardcoded 1, and only once per convert.
    expect(onCharged).toHaveBeenCalledTimes(1);
    expect(onCharged).toHaveBeenCalledWith(4);
  });

  it("does not charge when the account has insufficient credits", async () => {
    convertStatement.mockRejectedValue(
      new ApiError("insufficient", "no credits"),
    );
    const onCharged = vi.fn();
    renderConverter({ accountId: "web_test", onCharged });

    selectFileAndConvert();

    await waitFor(() =>
      expect(screen.getByRole("alert")).toBeInTheDocument(),
    );
    expect(onCharged).not.toHaveBeenCalled();
    expect(convertStatement).toHaveBeenCalledTimes(1);
  });
});
