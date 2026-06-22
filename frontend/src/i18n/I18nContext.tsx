import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  DEFAULT_LOCALE,
  detectInitialLocale,
  getTranslation,
  persistLocale,
  type LocaleCode,
  type Translation,
} from "./index";

interface I18nValue {
  locale: LocaleCode;
  t: Translation;
  setLocale: (l: LocaleCode) => void;
}

const I18nContext = createContext<I18nValue | null>(null);

export function I18nProvider({
  children,
  initialLocale,
}: {
  children: ReactNode;
  initialLocale?: LocaleCode;
}) {
  const [locale, setLocaleState] = useState<LocaleCode>(
    initialLocale ?? detectInitialLocale(),
  );

  const setLocale = useCallback((l: LocaleCode) => {
    setLocaleState(l);
    persistLocale(l);
    if (typeof document !== "undefined") {
      document.documentElement.lang = l;
    }
  }, []);

  const value = useMemo<I18nValue>(
    () => ({ locale, t: getTranslation(locale), setLocale }),
    [locale, setLocale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    // Fallback so components remain usable outside a provider (e.g. in tests).
    return {
      locale: DEFAULT_LOCALE,
      t: getTranslation(DEFAULT_LOCALE),
      setLocale: () => {},
    };
  }
  return ctx;
}
