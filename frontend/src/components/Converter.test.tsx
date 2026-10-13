import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { I18nProvider } from "../i18n/I18nContext";
import { LOCALES, LOCALE_ORDER, type LocaleCode } from "../i18n";

// Mock the API client so the component test drives the UI, not the network.
// Keep ApiError real (the component branches on `instanceof ApiError`).
const { convertStatement } = vi.hoisted(() => ({ convertStatement: vi.fn() }));
vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return { ...actual, convertStatement };
});

// Import after vi.mock so the component picks up the mocked module.
import { Converter } from "./Converter";
import { ApiError, type ConvertOutcome, type Reconciliation } from "../lib/api";
import { formatStatementMoney } from "../lib/reconciliation";

function renderConverter(props: Parameters<typeof Converter>[0], locale: LocaleCode = "en") {
  return render(
    <I18nProvider initialLocale={locale}>
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
    reconciliation: {
      status: "balanced",
      account_type: "deposit",
      terms: { opening: "2000.00", money_in: "3250.00", money_out: "0.00", closing: "5250.00" },
      printed_totals: { opening: "2000.00", money_in: "3250.00", money_out: "0.00", closing: "5250.00" },
      difference: "0.00",
      row_flags: [],
    },
    layout: "deposit_table",
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
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:mock"),
      revokeObjectURL: vi.fn(),
    });
  });

  afterEach(() => {
    delete window.umami;
    vi.restoreAllMocks();
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

  it("accepts only one batched conversion click and emits privacy-safe success events", async () => {
    const analytics = vi.fn();
    window.umami = { track: analytics };
    let complete!: (value: ConvertOutcome) => void;
    convertStatement.mockImplementation(() => new Promise<ConvertOutcome>((resolve) => { complete = resolve; }));
    const onCharged = vi.fn();
    renderConverter({ accountId: "web_test", onCharged });
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(input, { target: { files: [new File(["synthetic"], "private-filename.pdf")] } });
    const button = screen.getByRole("button", { name: "Convert" });
    act(() => { button.click(); button.click(); });
    expect(convertStatement).toHaveBeenCalledTimes(1);
    await act(async () => complete(outcome(1)));
    expect(onCharged).toHaveBeenCalledTimes(1);
    expect(analytics.mock.calls).toEqual([["file-selected"], ["convert-success", { balanced: "yes", layout: "deposit_table" }]]);
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(convertStatement).toHaveBeenCalledTimes(1);
    expect(analytics).toHaveBeenCalledTimes(2);
  });

  it.each([
    "Password-protected PDFs are not supported. Remove the password and try again.",
    "This PDF contains scanned pages without a text layer. Run OCR first.",
    "Multiple accounts were found. Convert each account separately.",
  ])("shows the backend's actionable PDF error: %s", async (detail) => {
    const analytics = vi.fn();
    window.umami = { track: analytics };
    convertStatement.mockRejectedValue(new ApiError("parse", detail));
    renderConverter({ accountId: "web_test" });
    selectFileAndConvert();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(detail));
    expect(analytics.mock.calls).toEqual([["file-selected"], ["convert-error"]]);
  });

  it.each([undefined, { metered: false as const, pages: 5 }])("does not refresh billing for an unmetered or absent charge: %s", async (charge) => {
    const converted = outcome(5);
    converted.result.charge = charge;
    convertStatement.mockResolvedValue(converted);
    const onCharged = vi.fn();
    renderConverter({ accountId: "web_test", onCharged });
    selectFileAndConvert();
    await waitFor(() => expect(screen.getByText("ACH PAYROLL DEPOSIT")).toBeInTheDocument());
    expect(onCharged).not.toHaveBeenCalled();
  });

  it.each(LOCALE_ORDER)("hides raw conversion billing conflicts behind the existing generic message in %s", async (locale) => {
    const detail = "Idempotency key belongs to another conversion.";
    convertStatement.mockRejectedValue(new ApiError("parse", detail, 409));
    renderConverter({ accountId: "web_test" }, locale);
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(input, { target: { files: [new File(["synthetic"], "statement.pdf")] } });
    fireEvent.click(screen.getByRole("button", { name: LOCALES[locale].convert_button }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(LOCALES[locale].convert_error_generic));
    expect(screen.getByRole("alert")).not.toHaveTextContent(detail);
  });

  it("hides raw billing or service-unavailable errors during conversion", async () => {
    const detail = "Stripe billing provider is unavailable because internal configuration is missing.";
    convertStatement.mockRejectedValue(new ApiError("parse", detail, 503));
    renderConverter({ accountId: "web_test" });
    selectFileAndConvert();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(LOCALES.en.convert_error_generic));
    expect(screen.getByRole("alert")).not.toHaveTextContent(detail);
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

  const states = ["deposit", "card", "not_balanced", "cannot_check"] as const;
  it.each(LOCALE_ORDER.flatMap((locale) => states.map((state) => [locale, state] as const)))
    ("shows the %s locale's %s status with only privacy-safe analytics properties", async (locale, state) => {
      const converted = outcome(1);
      const check = converted.result.reconciliation!;
      let template = LOCALES[locale].reconciliation_balanced_deposit;
      if (state === "card") {
        converted.result.reconciliation = {
          status: "balanced", account_type: "card", difference: "0.00", row_flags: [],
          terms: { previous: "2000.00", payments_credits: "500.00", purchases: "120.00", fees: "5.00", interest: "10.00", new: "1635.00" },
          printed_totals: { previous: "2000.00", payments_credits: "500.00", purchases: "120.00", fees: "5.00", interest: "10.00", new: "1635.00" },
        };
        converted.result.layout = "card_lines";
        template = LOCALES[locale].reconciliation_balanced_card;
      } else if (state === "not_balanced") {
        check.status = "not_balanced";
        check.difference = "-123.45";
        check.row_flags = [{ row_index: 0, flags: ["year_inferred_rollover", "sign_from_balance", "multiline_description"] }];
        template = LOCALES[locale].reconciliation_not_balanced;
      } else if (state === "cannot_check") {
        converted.result.reconciliation = undefined;
        converted.result.layout = "a-private-account-id";
        template = LOCALES[locale].reconciliation_cannot_check;
      }
      const analytics = vi.fn();
      window.umami = { track: analytics };
      convertStatement.mockResolvedValue(converted);
      renderConverter({}, locale);
      const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
      fireEvent.change(input, { target: { files: [new File(["synthetic"], "private-filename.pdf")] } });
      fireEvent.click(screen.getByRole("button", { name: LOCALES[locale].convert_button }));
      const expected = template.replace(/\{(\w+)\}/g, (_, key: string) => formatStatementMoney(
        key === "difference" ? "-123.45" : converted.result.reconciliation!.terms[key as keyof Reconciliation["terms"]]!, "USD", locale,
      ));
      await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(expected.replace(/\s/g, " ")));
      expect(document.querySelector(".results")?.firstElementChild).toHaveClass("reconciliation-status");
      const status = state === "deposit" || state === "card" ? "balanced" : state;
      expect(screen.getByRole("status")).toHaveAttribute("data-status", status);
      expect(analytics.mock.calls).toEqual([["file-selected"], ["convert-success", {
        balanced: status === "balanced" ? "yes" : status === "not_balanced" ? "no" : "unknown",
        layout: state === "card" ? "card_lines" : state === "cannot_check" ? "unknown" : "deposit_table",
      }]]);
      const row = screen.getByText("ACH PAYROLL DEPOSIT").closest("tr")!;
      if (state === "not_balanced") {
        expect(row).toHaveClass("flagged-row");
        for (const key of ["row_flag_year_inferred_rollover", "row_flag_sign_from_balance", "row_flag_multiline_description"] as const) {
          expect(row).toHaveTextContent(LOCALES[locale][key]);
          expect(row.title).toContain(LOCALES[locale][key]);
        }
      } else {
        expect(row).not.toHaveClass("flagged-row");
      }
    });

  it("shows a subtotal discrepancy when closing differences cancel", async () => {
    const converted = outcome(1);
    converted.result.reconciliation!.status = "not_balanced";
    converted.result.reconciliation!.check_differences = { money_in: "100.00", money_out: "100.00" };
    convertStatement.mockResolvedValue(converted);
    renderConverter({});
    selectFileAndConvert();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Doesn't balance: off by $100.00. Check the highlighted rows."));
  });

  it("includes flagged rows beyond the first 50 with their original indices", async () => {
    const converted = outcome(1);
    converted.result.transactions = Array.from({ length: 61 }, (_, index) => ({
      ...converted.result.transactions[0], description: `Synthetic transaction ${index}`,
    }));
    converted.result.summary.count = 61;
    converted.result.reconciliation!.status = "not_balanced";
    converted.result.reconciliation!.difference = "1.00";
    converted.result.reconciliation!.row_flags = [{ row_index: 60, flags: ["multiline_description"] }];
    convertStatement.mockResolvedValue(converted);
    renderConverter({});
    selectFileAndConvert();
    await waitFor(() => expect(screen.getByText("Synthetic transaction 60").closest("tr")).toHaveClass("flagged-row"));
    expect(document.querySelectorAll(".results tbody tr")).toHaveLength(51);
    expect(screen.getByText("Synthetic transaction 49")).toBeInTheDocument();
    expect(screen.queryByText("Synthetic transaction 50")).not.toBeInTheDocument();
    expect(screen.getByText("Synthetic transaction 60").closest("tr")).toHaveTextContent(LOCALES.en.row_flag_multiline_description);
  });
});
