import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { I18nProvider } from "./i18n/I18nContext";
import { LOCALES, LOCALE_ORDER, type LocaleCode } from "./i18n";

const { fetchAccount, openCheckout, navigateCheckout, fetchCheckoutStatus, fetchCheckoutAvailability, convertStatement } = vi.hoisted(() => ({
  fetchAccount: vi.fn(),
  openCheckout: vi.fn(),
  navigateCheckout: vi.fn(),
  fetchCheckoutStatus: vi.fn(),
  fetchCheckoutAvailability: vi.fn(),
  convertStatement: vi.fn(),
}));
vi.mock("./lib/api", async () => ({
  ...(await vi.importActual<typeof import("./lib/api")>("./lib/api")),
  fetchAccount,
  openCheckout,
  navigateCheckout,
  fetchCheckoutStatus,
  fetchCheckoutAvailability,
  convertStatement,
}));
import App from "./App";

const freeAccount = {
  id: "web_test", plan: "free", credits: 0, included_pages: 10,
  pages_used_this_cycle: 0, included_remaining: 10, pro: false,
};

async function renderApp(locale: LocaleCode = "en") {
  const rendered = render(<I18nProvider initialLocale={locale}><App /></I18nProvider>);
  await waitFor(() => expect(document.querySelector("#pricing")).not.toBeNull());
  return rendered;
}

describe("server-authoritative checkout", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("stx_account_id", "web_00000000-0000-4000-8000-000000000001");
    fetchAccount.mockReset().mockResolvedValue(freeAccount);
    fetchCheckoutAvailability.mockReset().mockResolvedValue(true);
    convertStatement.mockReset();
    openCheckout.mockReset();
    navigateCheckout.mockReset();
    fetchCheckoutStatus.mockReset().mockResolvedValue({ session_id: "cs_test_1", sku: "pack_50", status: "pending" });
  });
  afterEach(() => {
    delete window.umami;
    window.history.replaceState({}, "", "/");
    vi.unstubAllGlobals();
  });

  it.each(LOCALE_ORDER)("hides all billing UI in %s when checkout is unavailable and makes no account requests", async (locale) => {
    fetchCheckoutAvailability.mockResolvedValue(false);
    localStorage.removeItem("stx_account_id");
    window.history.replaceState({}, "", "/?checkout=success&session_id=cs_old");
    render(<I18nProvider initialLocale={locale}><App /></I18nProvider>);
    await act(async () => {});
    fireEvent.focus(window);
    expect(fetchCheckoutAvailability).toHaveBeenCalledTimes(1);
    expect(document.querySelector("#pricing")).toBeNull();
    expect(document.querySelectorAll('a[href="#pricing"]')).toHaveLength(0);
    expect(screen.queryByLabelText(LOCALES[locale].account_title)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: LOCALES[locale].convert_button })).toBeInTheDocument();
    expect(screen.getByText(LOCALES[locale].conversion_no_payment)).toBeInTheDocument();
    expect(fetchAccount).not.toHaveBeenCalled();
    expect(fetchCheckoutStatus).not.toHaveBeenCalled();
    expect(openCheckout).not.toHaveBeenCalled();
    expect(localStorage.getItem("stx_account_id")).toMatch(/^web_[0-9a-f-]{36}$/);
  });

  it.each(LOCALE_ORDER)("shows hosted management and billing disclosure in %s", async (locale) => {
    fetchAccount.mockResolvedValue({ ...freeAccount, plan: "starter", pro: true, management_available: true });
    await renderApp(locale);
    await waitFor(() => expect(screen.getByRole("button", { name: LOCALES[locale].billing_manage })).toBeInTheDocument());
    expect(screen.getByText(LOCALES[locale].billing_recovery)).toBeInTheDocument();
    expect(screen.getByText(LOCALES[locale].privacy_billing)).toBeInTheDocument();
    expect(screen.queryByText(LOCALES[locale].conversion_no_payment)).not.toBeInTheDocument();
  });

  it.each(LOCALE_ORDER)("blocks payment when storage is unavailable in %s while conversion remains usable", async (locale) => {
    await renderApp(locale);
    fireEvent.change(document.querySelector<HTMLInputElement>('input[type="file"]')!, { target: { files: [new File(["synthetic"], "synthetic.pdf")] } });
    const blocked = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    try {
      fireEvent.click(screen.getAllByRole("button", { name: LOCALES[locale].pricing_buy })[0]);
      expect(screen.getByRole("alert")).toHaveTextContent(LOCALES[locale].billing_storage_error);
      expect(openCheckout).not.toHaveBeenCalled();
      expect(screen.getByRole("button", { name: LOCALES[locale].convert_button })).toBeEnabled();
    } finally { blocked.mockRestore(); }
  });

  it("recovers the initial in-memory capability after storage becomes available in the same tab", async () => {
    localStorage.clear();
    const blocked = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    await renderApp();
    fireEvent.click(screen.getAllByRole("button", { name: LOCALES.en.pricing_buy })[0]);
    expect(openCheckout).not.toHaveBeenCalled();
    blocked.mockRestore();
    openCheckout.mockResolvedValue({ session_id: "cs_test_recovered", checkout_url: "https://checkout.stripe.com/synthetic", mode: "test", provider: "stripe" });
    fireEvent.click(screen.getAllByRole("button", { name: LOCALES.en.pricing_buy })[0]);
    await waitFor(() => expect(openCheckout).toHaveBeenCalledTimes(1));
    expect(openCheckout.mock.calls[0][0]).toBe(localStorage.getItem("stx_account_id"));
    expect(navigateCheckout).toHaveBeenCalled();
  });

  it.each(["starter", "business", "firm", "pack_50", "pack_200", "pack_1000"])("all six paid SKUs can open checkout: %s", async (sku) => {
    openCheckout.mockResolvedValue({ session_id: "cs_test_synthetic", checkout_url: "https://checkout.stripe.com/synthetic", mode: "test", provider: "stripe" });
    await renderApp();
    const ids = ["free", "starter", "business", "firm", "pack_50", "pack_200", "pack_1000"];
    const buttons = [...document.querySelectorAll<HTMLButtonElement>(".plan-card button, .pack-card button")];
    fireEvent.click(buttons[ids.indexOf(sku)]);
    await waitFor(() => expect(openCheckout).toHaveBeenCalledWith(expect.stringMatching(/^web_/), sku, expect.any(String)));
    expect(navigateCheckout).toHaveBeenCalled();
  });

  it("fails closed if the pricing availability request fails", async () => {
    fetchCheckoutAvailability.mockRejectedValue(new Error("Backend billing configuration is secret"));
    render(<I18nProvider initialLocale="en"><App /></I18nProvider>);
    await act(async () => {});
    expect(document.querySelector("#pricing")).toBeNull();
    expect(document.querySelectorAll('a[href="#pricing"]')).toHaveLength(0);
    expect(screen.queryByLabelText(LOCALES.en.account_title)).not.toBeInTheDocument();
    expect(fetchAccount).not.toHaveBeenCalled();
    expect(fetchCheckoutStatus).not.toHaveBeenCalled();
    expect(openCheckout).not.toHaveBeenCalled();
    expect(screen.queryByText("Backend billing configuration is secret")).not.toBeInTheDocument();
    expect(screen.queryByText(LOCALES.en.conversion_no_payment)).not.toBeInTheDocument();
  });

  it("waits for authoritative availability and ignores its response after unmount", async () => {
    let complete!: (available: boolean) => void;
    fetchCheckoutAvailability.mockImplementation(() => new Promise<boolean>((resolve) => { complete = resolve; }));
    localStorage.removeItem("stx_account_id");
    window.history.replaceState({}, "", "/?checkout=success&session_id=cs_old");
    const rendered = render(<I18nProvider initialLocale="en"><App /></I18nProvider>);
    fireEvent.focus(window);
    expect(screen.queryByText(LOCALES.en.conversion_no_payment)).not.toBeInTheDocument();
    expect(document.querySelector("#pricing")).toBeNull();
    expect(document.querySelectorAll('a[href="#pricing"]')).toHaveLength(0);
    expect(screen.queryByLabelText(LOCALES.en.account_title)).not.toBeInTheDocument();
    expect(fetchAccount).not.toHaveBeenCalled();
    expect(fetchCheckoutStatus).not.toHaveBeenCalled();
    rendered.unmount();
    await act(async () => complete(true));
    expect(fetchAccount).not.toHaveBeenCalled();
    expect(fetchCheckoutStatus).not.toHaveBeenCalled();
    expect(openCheckout).not.toHaveBeenCalled();
    expect(localStorage.getItem("stx_account_id")).toMatch(/^web_[0-9a-f-]{36}$/);
  });

  it("continues unmetered conversion without creating or refreshing a backend account", async () => {
    fetchCheckoutAvailability.mockResolvedValue(false);
    convertStatement.mockResolvedValue({
      result: { transactions: [], summary: { count: 0, total_debit: "0", total_credit: "0", net: "0", currency: "USD", start_date: null, end_date: null }, charge: { metered: false, pages: 5 } },
      blob: null, filename: "statement.xlsx",
    });
    render(<I18nProvider initialLocale="en"><App /></I18nProvider>);
    await act(async () => {});
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(input, { target: { files: [new File(["synthetic"], "statement.pdf")] } });
    fireEvent.click(screen.getByRole("button", { name: "Convert" }));
    await waitFor(() => expect(screen.getByText("Preview")).toBeInTheDocument());
    expect(convertStatement).toHaveBeenCalledWith(expect.any(File), { accountId: localStorage.getItem("stx_account_id"), fmt: "xlsx", currency: "USD" });
    expect(fetchAccount).not.toHaveBeenCalled();
    expect(fetchCheckoutStatus).not.toHaveBeenCalled();
    expect(openCheckout).not.toHaveBeenCalled();
  });

  it("uses the same unique account for a conversion before availability resolves and the later enabled account", async () => {
    let complete!: (available: boolean) => void;
    fetchCheckoutAvailability.mockImplementation(() => new Promise<boolean>((resolve) => { complete = resolve; }));
    localStorage.removeItem("stx_account_id");
    convertStatement.mockResolvedValue({
      result: { transactions: [], summary: { count: 0, total_debit: "0", total_credit: "0", net: "0", currency: "USD", start_date: null, end_date: null }, charge: { pages: 1, from_included: 1, from_credits: 0, credits_after: 0 } },
      blob: null, filename: "statement.xlsx",
    });
    render(<I18nProvider initialLocale="en"><App /></I18nProvider>);
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(input, { target: { files: [new File(["synthetic"], "pending.pdf")] } });
    fireEvent.click(screen.getByRole("button", { name: "Convert" }));
    await waitFor(() => expect(screen.getByText("Preview")).toBeInTheDocument());
    const conversionAccountId = convertStatement.mock.calls[0][1].accountId;
    expect(conversionAccountId).toMatch(/^web_[0-9a-f-]{36}$/);
    expect(fetchAccount).not.toHaveBeenCalled();
    expect(document.querySelector("#pricing")).toBeNull();
    await act(async () => complete(true));
    await waitFor(() => expect(fetchAccount).toHaveBeenCalledWith(conversionAccountId));
    expect(localStorage.getItem("stx_account_id")).toBe(conversionAccountId);
  });

  it("keeps a unique stable conversion identity when pricing availability fails", async () => {
    fetchCheckoutAvailability.mockRejectedValue(new Error("Pricing request failed"));
    localStorage.removeItem("stx_account_id");
    convertStatement.mockResolvedValue({
      result: { transactions: [], summary: { count: 0, total_debit: "0", total_credit: "0", net: "0", currency: "USD", start_date: null, end_date: null }, charge: { pages: 1, from_included: 1, from_credits: 0, credits_after: 0 } },
      blob: null, filename: "statement.xlsx",
    });
    render(<I18nProvider initialLocale="en"><App /></I18nProvider>);
    await act(async () => {});
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    for (const name of ["first.pdf", "second.pdf"]) {
      fireEvent.change(input, { target: { files: [new File(["synthetic"], name)] } });
      fireEvent.click(screen.getByRole("button", { name: "Convert" }));
      await waitFor(() => expect(screen.getByText("Preview")).toBeInTheDocument());
    }
    expect(convertStatement).toHaveBeenCalledTimes(2);
    const firstAccountId = convertStatement.mock.calls[0][1].accountId;
    expect(firstAccountId).toMatch(/^web_[0-9a-f-]{36}$/);
    expect(convertStatement.mock.calls[1][1].accountId).toBe(firstAccountId);
    expect(fetchAccount).not.toHaveBeenCalled();
    expect(fetchCheckoutStatus).not.toHaveBeenCalled();
    expect(openCheckout).not.toHaveBeenCalled();
    expect(document.querySelector("#pricing")).toBeNull();
  });

  it.each(LOCALE_ORDER)("shows only the localized checkout error in %s", async (locale) => {
    openCheckout.mockRejectedValue(new Error("Raw secret backend configuration: STRIPE_OMITTED"));
    await renderApp(locale);
    fireEvent.click(screen.getAllByRole("button", { name: LOCALES[locale].pricing_choose_plan })[1]);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(LOCALES[locale].checkout_error));
    expect(screen.getByRole("alert")).not.toHaveTextContent("STRIPE_OMITTED");
    expect(screen.queryByText("Raw secret backend configuration: STRIPE_OMITTED")).not.toBeInTheDocument();
  });

  it("updates a checkout error when the visitor changes locale", async () => {
    openCheckout.mockRejectedValue(new Error("Raw backend checkout detail"));
    await renderApp();
    fireEvent.click(screen.getAllByRole("button", { name: LOCALES.en.pricing_choose_plan })[1]);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(LOCALES.en.checkout_error));
    fireEvent.change(screen.getByLabelText("Select language"), { target: { value: "ja" } });
    expect(screen.getByRole("alert")).toHaveTextContent(LOCALES.ja.checkout_error);
    expect(screen.getByRole("alert")).not.toHaveTextContent("Raw backend checkout detail");
  });

  it("does not start a checkout after an in-flight status response arrives after unmount", async () => {
    const accountId = localStorage.getItem("stx_account_id")!;
    const requestId = "00000000-0000-4000-8000-000000000099";
    localStorage.setItem(`stx_checkout_${accountId}_pack_50`, requestId);
    localStorage.setItem(`stx_checkout_session_${accountId}_pack_50`, JSON.stringify({ requestId, sessionId: "cs_current" }));
    let complete!: (status: unknown) => void;
    fetchCheckoutStatus.mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
    const rendered = await renderApp();
    fireEvent.click(screen.getAllByRole("button", { name: "Buy" })[0]);
    await waitFor(() => expect(fetchCheckoutStatus).toHaveBeenCalledTimes(1));
    rendered.unmount();
    await act(async () => complete({ session_id: "cs_current", sku: "pack_50", status: "pending" }));
    expect(openCheckout).not.toHaveBeenCalled();
    expect(navigateCheckout).not.toHaveBeenCalled();
  });

  it("does not grant a paid plan when checkout fails", async () => {
    openCheckout.mockRejectedValue(new Error("Checkout is not configured"));
    await renderApp();
    fireEvent.click(screen.getAllByRole("button", { name: "Choose plan" })[1]);
    await waitFor(() => expect(openCheckout).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText("Your account")).toHaveTextContent("Free");
    expect(screen.getByRole("alert")).toHaveTextContent(LOCALES.en.checkout_error);
  });

  it("coalesces double upgrade clicks before React commits busy state", async () => {
    openCheckout.mockImplementation(() => new Promise(() => {}));
    await renderApp();
    const button = screen.getAllByRole("button", { name: "Choose plan" })[1];
    act(() => {
      button.click();
      button.click();
    });
    await waitFor(() => expect(openCheckout).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText("Your account")).toHaveTextContent("Free");
  });

  it("reuses a checkout intent after failure and emits only the requested events", async () => {
    const analytics = vi.fn();
    window.umami = { track: analytics };
    openCheckout.mockRejectedValueOnce(new Error("Network error"))
      .mockResolvedValueOnce({ session_id: "cs_test_1", checkout_url: "https://checkout.stripe.com/c/pay/cs_test_1", mode: "test", provider: "stripe" });
    await renderApp();
    const button = screen.getAllByRole("button", { name: "Choose plan" })[1];
    fireEvent.click(button);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(LOCALES.en.checkout_error));
    fireEvent.click(button);
    await waitFor(() => expect(navigateCheckout).toHaveBeenCalledTimes(1));
    expect(openCheckout.mock.calls[0]).toEqual(openCheckout.mock.calls[1]);
    expect(analytics.mock.calls).toEqual([["upgrade-click"], ["upgrade-click"], ["checkout-opened"]]);
    expect(screen.getByLabelText("Your account")).toHaveTextContent("Free");
  });

  it.each(["fulfilled", "expired", "cancelled"])("allows another pack only after the backend confirms the prior session is %s", async (status) => {
    openCheckout.mockResolvedValueOnce({ session_id: "cs_test_1", checkout_url: "https://checkout.stripe.com/c/pay/cs_test_1", mode: "test", provider: "stripe" })
      .mockResolvedValueOnce({ session_id: "cs_test_2", checkout_url: "https://checkout.stripe.com/c/pay/cs_test_2", mode: "test", provider: "stripe" });
    fetchCheckoutStatus.mockResolvedValue({ session_id: "cs_test_1", sku: "pack_50", status });
    await renderApp();
    const button = screen.getAllByRole("button", { name: "Buy" })[0];
    fireEvent.click(button);
    await waitFor(() => expect(navigateCheckout).toHaveBeenCalledTimes(1));
    fireEvent.click(button);
    await waitFor(() => expect(navigateCheckout).toHaveBeenCalledTimes(2));
    expect(openCheckout.mock.calls[0][2]).not.toEqual(openCheckout.mock.calls[1][2]);
  });

  it("keeps a payable pending session and its request key on retry", async () => {
    openCheckout.mockResolvedValue({ session_id: "cs_test_1", checkout_url: "https://checkout.stripe.com/c/pay/cs_test_1", mode: "test", provider: "stripe" });
    await renderApp();
    const button = screen.getAllByRole("button", { name: "Buy" })[0];
    fireEvent.click(button);
    await waitFor(() => expect(navigateCheckout).toHaveBeenCalledTimes(1));
    fireEvent.click(button);
    await waitFor(() => expect(navigateCheckout).toHaveBeenCalledTimes(2));
    expect(fetchCheckoutStatus).toHaveBeenCalledTimes(1);
    expect(openCheckout.mock.calls[0]).toEqual(openCheckout.mock.calls[1]);
  });

  it("does not rotate an intent when checkout status is unavailable", async () => {
    openCheckout.mockResolvedValue({ session_id: "cs_test_1", checkout_url: "https://checkout.stripe.com/c/pay/cs_test_1", mode: "test", provider: "stripe" });
    await renderApp();
    const button = screen.getAllByRole("button", { name: "Buy" })[0];
    fireEvent.click(button);
    await waitFor(() => expect(navigateCheckout).toHaveBeenCalledTimes(1));
    fetchCheckoutStatus.mockRejectedValueOnce(new Error("Status temporarily unavailable"));
    fireEvent.click(button);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(LOCALES.en.checkout_error));
    expect(openCheckout).toHaveBeenCalledTimes(1);
    fireEvent.click(button);
    await waitFor(() => expect(openCheckout).toHaveBeenCalledTimes(2));
    expect(openCheckout.mock.calls[0]).toEqual(openCheckout.mock.calls[1]);
  });

  it("retains a newer tab's saved session while reconciling an older in-memory checkout", async () => {
    const accountId = localStorage.getItem("stx_account_id")!;
    const newer = { requestId: "00000000-0000-4000-8000-000000000099", sessionId: "cs_newer_tab" };
    openCheckout.mockResolvedValueOnce({ session_id: "cs_test_1", checkout_url: "https://checkout.stripe.com/c/pay/cs_test_1", mode: "test", provider: "stripe" })
      .mockRejectedValueOnce(new Error("Provider request failed"));
    fetchCheckoutStatus.mockResolvedValue({ session_id: "cs_test_1", sku: "pack_50", status: "fulfilled" });
    await renderApp();
    const button = screen.getAllByRole("button", { name: "Buy" })[0];
    fireEvent.click(button);
    await waitFor(() => expect(navigateCheckout).toHaveBeenCalledTimes(1));
    // A different tab creates a newer purchase while this App retains the old one.
    localStorage.setItem(`stx_checkout_${accountId}_pack_50`, newer.requestId);
    localStorage.setItem(`stx_checkout_session_${accountId}_pack_50`, JSON.stringify(newer));
    fireEvent.click(button);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(LOCALES.en.checkout_error));
    expect(openCheckout.mock.calls[1][2]).toBe(newer.requestId);
    expect(localStorage.getItem(`stx_checkout_${accountId}_pack_50`)).toBe(newer.requestId);
    expect(JSON.parse(localStorage.getItem(`stx_checkout_session_${accountId}_pack_50`)!)).toEqual(newer);
  });

  it("does not clear a current intent from an old fulfilled checkout URL", async () => {
    const accountId = localStorage.getItem("stx_account_id")!;
    const requestId = "00000000-0000-4000-8000-000000000099";
    localStorage.setItem(`stx_checkout_${accountId}_pack_50`, requestId);
    localStorage.setItem(`stx_checkout_session_${accountId}_pack_50`, JSON.stringify({ requestId, sessionId: "cs_current" }));
    window.history.replaceState({}, "", "/?checkout=success&session_id=cs_old");
    fetchCheckoutStatus.mockImplementation((_accountId: string, sessionId: string) => Promise.resolve({ session_id: sessionId, sku: "pack_50", status: sessionId === "cs_old" ? "fulfilled" : "pending" }));
    openCheckout.mockResolvedValue({ session_id: "cs_current", checkout_url: "https://checkout.stripe.com/c/pay/cs_current", mode: "test", provider: "stripe" });
    await renderApp();
    await waitFor(() => expect(fetchAccount).toHaveBeenCalled());
    fireEvent.click(screen.getAllByRole("button", { name: "Buy" })[0]);
    await waitFor(() => expect(openCheckout).toHaveBeenCalledTimes(1));
    expect(openCheckout.mock.calls[0][2]).toBe(requestId);
  });

  it("shows Pro only when the backend account reports a paid entitlement", async () => {
    fetchAccount.mockResolvedValue({ ...freeAccount, plan: "starter", pro: true });
    await renderApp();
    await waitFor(() => expect(screen.getByLabelText("Your account")).toHaveTextContent("Pro"));
  });

  it("still refreshes server entitlements when a return URL has an unknown checkout session", async () => {
    window.history.replaceState({}, "", "/?checkout=success&session_id=cs_unknown");
    fetchCheckoutStatus.mockRejectedValue(new Error("Checkout not found"));
    fetchAccount.mockResolvedValue({ ...freeAccount, plan: "starter", pro: true });
    await renderApp();
    await waitFor(() => expect(screen.getByLabelText("Your account")).toHaveTextContent("Pro"));
  });

  it("ignores forged local entitlement and checkout success URL", async () => {
    localStorage.setItem("stx_account", JSON.stringify({
      planId: "business", credits: 9999, pagesUsedThisCycle: 0,
    }));
    window.history.replaceState({}, "", "/?checkout=success");
    await renderApp();
    await waitFor(() => expect(fetchAccount).toHaveBeenCalled());
    expect(screen.getByLabelText("Your account")).toHaveTextContent("Free");
    expect(screen.getByLabelText("Your account")).toHaveTextContent("Credits: 0");
    window.history.replaceState({}, "", "/");
  });
});
