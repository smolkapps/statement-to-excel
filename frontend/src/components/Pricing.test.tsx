import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { Pricing } from "./Pricing";
import { AccountChip } from "./AccountChip";
import { I18nProvider } from "../i18n/I18nContext";
import { LOCALES, LOCALE_ORDER, type LocaleCode } from "../i18n";
import { PRICING, formatUsd, newAccount } from "../lib/pricing";

function renderWithI18n(ui: React.ReactElement, locale: LocaleCode = "en") {
  return render(<I18nProvider initialLocale={locale}>{ui}</I18nProvider>);
}

describe("Pricing", () => {
  it.each(LOCALE_ORDER)("describes total Free allowance and preserves paid monthly terms in %s", (locale) => {
    const t = LOCALES[locale];
    renderWithI18n(<><Pricing /><AccountChip account={newAccount()} /></>, locale);
    expect(screen.getByRole("heading", { name: t.pricing_plans_title })).toBeInTheDocument();
    for (const plan of PRICING.plans) {
      const card = screen.getByRole("heading", { name: plan.name }).closest("article")!;
      expect(card.querySelector(".plan-price")).toHaveTextContent(formatUsd(plan.monthly_price_usd));
      if (plan.id === "free") {
        expect(card.querySelector(".per")).toBeNull();
        expect(within(card).getByText(`${plan.included_pages} ${t.pricing_free_pages}`, { exact: true })).toBeInTheDocument();
        expect(card).not.toHaveTextContent(t.pricing_included_pages);
        expect(card).not.toHaveTextContent(t.pricing_per_month);
      } else {
        expect(card.querySelector(".per")).toHaveTextContent(t.pricing_per_month);
        expect(within(card).getByText(`${plan.included_pages} ${t.pricing_included_pages}`, { exact: true })).toBeInTheDocument();
        expect(card).toHaveTextContent(t.pricing_overage);
      }
    }
    expect(screen.getByLabelText(t.account_title)).toHaveTextContent(`${t.account_included_remaining}: 3`);
    expect(screen.getByText(t.billing_recovery)).toBeInTheDocument();
    for (const pack of PRICING.credit_packs) {
      const card = screen.getByRole("heading", { name: pack.credits.toLocaleString() }).closest("article")!;
      expect(card.querySelector(".pack-price")).toHaveTextContent(formatUsd(pack.price_usd));
    }
  });

  it("renders all plans and packs with business-tier prices", () => {
    renderWithI18n(<Pricing />);
    expect(screen.getByText("Business")).toBeInTheDocument();
    expect(screen.getByText("Firm")).toBeInTheDocument();
    // $79 business plan + $400 pack are visible.
    expect(screen.getByText("$79")).toBeInTheDocument();
    expect(screen.getByText("$400")).toBeInTheDocument();
  });

  it("fires onBuyPack with the pack id", () => {
    const onBuyPack = vi.fn();
    renderWithI18n(<Pricing onBuyPack={onBuyPack} />);
    const buyButtons = screen.getAllByRole("button", { name: "Buy" });
    fireEvent.click(buyButtons[0]);
    expect(onBuyPack).toHaveBeenCalledWith("pack_50");
  });

  it("fires onChoosePlan with the plan id", () => {
    const onChoosePlan = vi.fn();
    renderWithI18n(<Pricing onChoosePlan={onChoosePlan} />);
    const planButtons = screen.getAllByRole("button", { name: "Choose plan" });
    fireEvent.click(planButtons[1]);
    expect(onChoosePlan).toHaveBeenCalledWith("starter");
  });

  it("localizes the heading into Japanese", () => {
    renderWithI18n(<Pricing />, "ja");
    expect(screen.getByText("ビジネス向けの料金")).toBeInTheDocument();
  });
});
