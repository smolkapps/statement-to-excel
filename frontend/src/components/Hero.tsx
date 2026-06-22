import { useI18n } from "../i18n/I18nContext";

export function Hero() {
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
        <a href="#pricing" className="btn btn-ghost">
          {t.hero_secondary_cta}
        </a>
      </div>
      <p className="trust">{t.hero_trust}</p>
    </section>
  );
}
