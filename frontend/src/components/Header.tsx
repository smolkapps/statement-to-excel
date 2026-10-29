import { useI18n } from "../i18n/I18nContext";
import { LOCALE_ORDER, LOCALES, type LocaleCode } from "../i18n";
import { useLayoutEffect, useRef } from "react";

export function Header({ showPricing = false }: { showPricing?: boolean }) {
  const { t, locale, setLocale } = useI18n();
  const header = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const element = header.current;
    if (!element) return;
    const measure = () => element.parentElement?.style.setProperty("--header-height", `${element.getBoundingClientRect().height}px`);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return (
    <header className="site-header" ref={header}>
      <a href="#top" className="brand" aria-label="Statement→Excel home">
        <span className="brand-mark" aria-hidden="true">
          ⇲
        </span>
        <span className="brand-name">Statement→Excel</span>
      </a>
      <nav className="nav" aria-label="Primary">
        <a href="#product">{t.nav_product}</a>
        {showPricing && <a href="#pricing">{t.nav_pricing}</a>}
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
