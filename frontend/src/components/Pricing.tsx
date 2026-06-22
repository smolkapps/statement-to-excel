import { useI18n } from "../i18n/I18nContext";
import { PRICING, formatUsd } from "../lib/pricing";

interface Props {
  onBuyPack?: (packId: string) => void;
  onChoosePlan?: (planId: string) => void;
}

export function Pricing({ onBuyPack, onChoosePlan }: Props) {
  const { t } = useI18n();
  return (
    <section className="pricing" id="pricing">
      <h2>{t.pricing_title}</h2>
      <p className="pricing-sub">{t.pricing_subtitle}</p>

      <h3 className="pricing-section-title">{t.pricing_plans_title}</h3>
      <div className="plan-grid">
        {PRICING.plans.map((plan) => (
          <article
            key={plan.id}
            className={`plan-card${plan.id === "business" ? " featured" : ""}`}
          >
            <h4>{plan.name}</h4>
            <p className="plan-price">
              {formatUsd(plan.monthly_price_usd)}
              <span className="per">{t.pricing_per_month}</span>
            </p>
            <ul className="plan-feats">
              <li>
                {plan.included_pages} {t.pricing_included_pages}
              </li>
              {Number(plan.overage_per_page_usd) > 0 && (
                <li>
                  {formatUsd(plan.overage_per_page_usd)} {t.pricing_overage}
                </li>
              )}
            </ul>
            <button
              className="btn btn-outline"
              onClick={() => onChoosePlan?.(plan.id)}
            >
              {t.pricing_choose_plan}
            </button>
          </article>
        ))}
      </div>

      <h3 className="pricing-section-title">{t.pricing_credits_title}</h3>
      <p className="pricing-explainer">{t.pricing_credit_explainer}</p>
      <div className="pack-grid">
        {PRICING.credit_packs.map((pack) => (
          <article key={pack.id} className="pack-card">
            <h4>{pack.credits.toLocaleString()}</h4>
            <p className="pack-price">{formatUsd(pack.price_usd)}</p>
            <p className="pack-unit">
              {formatUsd(pack.per_credit_usd)} {t.pricing_credits_each}
            </p>
            <button
              className="btn btn-primary"
              onClick={() => onBuyPack?.(pack.id)}
            >
              {t.pricing_buy}
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}
