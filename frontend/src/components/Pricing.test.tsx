import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { Pricing } from "./Pricing";
import { I18nProvider } from "../i18n/I18nContext";

function renderWithI18n(ui: React.ReactElement, locale: "en" | "ja" = "en") {
  return render(<I18nProvider initialLocale={locale}>{ui}</I18nProvider>);
}

describe("Pricing", () => {
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
    fireEvent.click(planButtons[0]);
    expect(onChoosePlan).toHaveBeenCalledWith("free");
  });

  it("localizes the heading into Japanese", () => {
    renderWithI18n(<Pricing />, "ja");
    expect(screen.getByText("ビジネス向けの料金")).toBeInTheDocument();
  });
});
