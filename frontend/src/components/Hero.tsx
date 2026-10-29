import { useI18n } from "../i18n/I18nContext";

export function Hero({ showPricing = false, unmetered = false }: { showPricing?: boolean; unmetered?: boolean }) {
  const { t } = useI18n();
  return (
    <section className="hero" id="product">
      <p className="eyebrow">{t.hero_eyebrow}</p>
      <h1>{t.hero_title}</h1>
      <p className="lede">{t.hero_subtitle}</p>
      <div className="hero-actions">
        <a href="#convert" className="btn btn-primary">
          {t.hero_cta}
        </a>
        {showPricing && (
          <a href="#pricing" className="btn btn-ghost">
            {t.hero_secondary_cta}
          </a>
        )}
      </div>
      <p className="trust">{t.hero_trust}</p>
      {unmetered && <p className="availability-note">{t.conversion_no_payment}</p>}
    </section>
  );
}
