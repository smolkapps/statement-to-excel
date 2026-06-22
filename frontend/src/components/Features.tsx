import { useI18n } from "../i18n/I18nContext";

export function Features() {
  const { t } = useI18n();
  const items = [
    {
      icon: "✓",
      title: t.feature_accuracy_title,
      body: t.feature_accuracy_body,
    },
    {
      icon: "🔒",
      title: t.feature_private_title,
      body: t.feature_private_body,
    },
    {
      icon: "⤓",
      title: t.feature_formats_title,
      body: t.feature_formats_body,
    },
  ];
  return (
    <section className="features" aria-label={t.nav_product}>
      <div className="feature-grid">
        {items.map((it) => (
          <article key={it.title} className="feature-card">
            <div className="feature-icon" aria-hidden="true">
              {it.icon}
            </div>
            <h3>{it.title}</h3>
            <p>{it.body}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

export function HowItWorks() {
  const { t } = useI18n();
  return (
    <section className="how">
      <h2>{t.how_title}</h2>
      <ol className="how-steps">
        <li>{t.how_step1}</li>
        <li>{t.how_step2}</li>
        <li>{t.how_step3}</li>
      </ol>
    </section>
  );
}
