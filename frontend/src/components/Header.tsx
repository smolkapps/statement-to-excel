import { useI18n } from "../i18n/I18nContext";
import { LOCALE_ORDER, LOCALES, type LocaleCode } from "../i18n";

export function Header() {
  const { t, locale, setLocale } = useI18n();
  return (
    <header className="site-header">
      <a href="#top" className="brand" aria-label="statement-to-excel home">
        <span className="brand-mark" aria-hidden="true">
          ⇲
        </span>
        <span className="brand-name">statement&#8203;-to-excel</span>
      </a>
      <nav className="nav" aria-label="Primary">
        <a href="#product">{t.nav_product}</a>
        <a href="#pricing">{t.nav_pricing}</a>
        <a href="#convert" className="nav-cta">
          {t.nav_convert}
        </a>
      </nav>
      <label className="locale-switcher">
        <span className="visually-hidden">Language</span>
        <select
          value={locale}
          onChange={(e) => setLocale(e.target.value as LocaleCode)}
          aria-label="Select language"
        >
          {LOCALE_ORDER.map((code) => (
            <option key={code} value={code}>
              {LOCALES[code].locale_name}
            </option>
          ))}
        </select>
      </label>
    </header>
  );
}
