import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { I18nProvider } from "./i18n/I18nContext";

const { fetchAccount, openCheckout, navigateCheckout, fetchCheckoutStatus } = vi.hoisted(() => ({
  fetchAccount: vi.fn(),
  openCheckout: vi.fn(),
  navigateCheckout: vi.fn(),
  fetchCheckoutStatus: vi.fn(),
}));
vi.mock("./lib/api", async () => ({
  ...(await vi.importActual<typeof import("./lib/api")>("./lib/api")),
  fetchAccount,
  openCheckout,
  navigateCheckout,
  fetchCheckoutStatus,
}));
import App from "./App";

const freeAccount = {
  id: "web_test", plan: "free", credits: 0, included_pages: 10,
  pages_used_this_cycle: 0, included_remaining: 10, pro: false,
};

function renderApp() {
  return render(<I18nProvider initialLocale="en"><App /></I18nProvider>);
}

describe("server-authoritative checkout", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("stx_account_id", "web_00000000-0000-4000-8000-000000000001");
    fetchAccount.mockReset().mockResolvedValue(freeAccount);
    openCheckout.mockReset();
    navigateCheckout.mockReset();
    fetchCheckoutStatus.mockReset().mockResolvedValue({ session_id: "cs_test_1", sku: "pack_50", status: "pending" });
  });
  afterEach(() => {
    delete window.umami;
    window.history.replaceState({}, "", "/");
    vi.unstubAllGlobals();
  });

  it("does not grant a paid plan when checkout fails", async () => {
    openCheckout.mockRejectedValue(new Error("Checkout is not configured"));
    renderApp();
    fireEvent.click(screen.getAllByRole("button", { name: "Choose plan" })[1]);
    await waitFor(() => expect(openCheckout).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText("Your account")).toHaveTextContent("Free");
    expect(screen.getByRole("alert")).toHaveTextContent("Checkout is not configured");
  });

  it("coalesces double upgrade clicks before React commits busy state", async () => {
    openCheckout.mockImplementation(() => new Promise(() => {}));
    renderApp();
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
    renderApp();
    const button = screen.getAllByRole("button", { name: "Choose plan" })[1];
    fireEvent.click(button);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Network error"));
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
    renderApp();
    const button = screen.getAllByRole("button", { name: "Buy" })[0];
    fireEvent.click(button);
    await waitFor(() => expect(navigateCheckout).toHaveBeenCalledTimes(1));
    fireEvent.click(button);
    await waitFor(() => expect(navigateCheckout).toHaveBeenCalledTimes(2));
    expect(openCheckout.mock.calls[0][2]).not.toEqual(openCheckout.mock.calls[1][2]);
  });

  it("keeps a payable pending session and its request key on retry", async () => {
    openCheckout.mockResolvedValue({ session_id: "cs_test_1", checkout_url: "https://checkout.stripe.com/c/pay/cs_test_1", mode: "test", provider: "stripe" });
    renderApp();
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
    renderApp();
    const button = screen.getAllByRole("button", { name: "Buy" })[0];
    fireEvent.click(button);
    await waitFor(() => expect(navigateCheckout).toHaveBeenCalledTimes(1));
    fetchCheckoutStatus.mockRejectedValueOnce(new Error("Status temporarily unavailable"));
    fireEvent.click(button);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Status temporarily unavailable"));
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
    renderApp();
    const button = screen.getAllByRole("button", { name: "Buy" })[0];
    fireEvent.click(button);
    await waitFor(() => expect(navigateCheckout).toHaveBeenCalledTimes(1));
    // A different tab creates a newer purchase while this App retains the old one.
    localStorage.setItem(`stx_checkout_${accountId}_pack_50`, newer.requestId);
    localStorage.setItem(`stx_checkout_session_${accountId}_pack_50`, JSON.stringify(newer));
    fireEvent.click(button);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Provider request failed"));
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
    renderApp();
    await waitFor(() => expect(fetchAccount).toHaveBeenCalled());
    fireEvent.click(screen.getAllByRole("button", { name: "Buy" })[0]);
    await waitFor(() => expect(openCheckout).toHaveBeenCalledTimes(1));
    expect(openCheckout.mock.calls[0][2]).toBe(requestId);
  });

  it("shows Pro only when the backend account reports a paid entitlement", async () => {
    fetchAccount.mockResolvedValue({ ...freeAccount, plan: "starter", pro: true });
    renderApp();
    await waitFor(() => expect(screen.getByLabelText("Your account")).toHaveTextContent("Pro"));
  });

  it("still refreshes server entitlements when a return URL has an unknown checkout session", async () => {
    window.history.replaceState({}, "", "/?checkout=success&session_id=cs_unknown");
    fetchCheckoutStatus.mockRejectedValue(new Error("Checkout not found"));
    fetchAccount.mockResolvedValue({ ...freeAccount, plan: "starter", pro: true });
    renderApp();
    await waitFor(() => expect(screen.getByLabelText("Your account")).toHaveTextContent("Pro"));
  });

  it("ignores forged local entitlement and checkout success URL", async () => {
    localStorage.setItem("stx_account", JSON.stringify({
      planId: "business", credits: 9999, pagesUsedThisCycle: 0,
    }));
    window.history.replaceState({}, "", "/?checkout=success");
    renderApp();
    await waitFor(() => expect(fetchAccount).toHaveBeenCalled());
    expect(screen.getByLabelText("Your account")).toHaveTextContent("Free");
    expect(screen.getByLabelText("Your account")).toHaveTextContent("Credits: 0");
    window.history.replaceState({}, "", "/");
  });
});
