import type { LocaleCode, Translation } from "./types";
import { en } from "./locales/en";
import { zh } from "./locales/zh";
import { ja } from "./locales/ja";
import { es } from "./locales/es";
import { it } from "./locales/it";

export type { LocaleCode, Translation } from "./types";

export const LOCALES: Record<LocaleCode, Translation> = { en, zh, ja, es, it };

export const LOCALE_ORDER: LocaleCode[] = ["en", "zh", "ja", "es", "it"];

export const DEFAULT_LOCALE: LocaleCode = "en";

const STORAGE_KEY = "stx_locale";

export function isLocaleCode(value: string | null | undefined): value is LocaleCode {
  return !!value && (LOCALE_ORDER as string[]).includes(value);
}

/**
 * Resolve the best locale from a list of candidates (e.g. navigator.languages),
 * matching on the primary subtag ("ja-JP" -> "ja"). Falls back to DEFAULT_LOCALE.
 */
export function resolveLocale(candidates: readonly string[]): LocaleCode {
  for (const raw of candidates) {
    const primary = raw.toLowerCase().split("-")[0];
    if (isLocaleCode(primary)) return primary;
  }
  return DEFAULT_LOCALE;
}

/** Detect the initial locale: stored preference first, then browser, then default. */
export function detectInitialLocale(): LocaleCode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (isLocaleCode(stored)) return stored;
  } catch {
    /* localStorage may be unavailable (SSR / privacy mode) */
  }
  const langs =
    typeof navigator !== "undefined"
      ? navigator.languages ?? [navigator.language]
      : [];
  return resolveLocale(langs);
}

export function persistLocale(locale: LocaleCode): void {
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    /* ignore */
  }
}

export function getTranslation(locale: LocaleCode): Translation {
  return LOCALES[locale] ?? LOCALES[DEFAULT_LOCALE];
}
