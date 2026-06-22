import { describe, expect, it } from "vitest";
import { en } from "./locales/en";
import {
  DEFAULT_LOCALE,
  getTranslation,
  isLocaleCode,
  LOCALES,
  LOCALE_ORDER,
  resolveLocale,
} from "./index";

const REQUIRED_KEYS = Object.keys(en) as (keyof typeof en)[];

describe("locale parity", () => {
  it("registers all five locales in order", () => {
    expect(LOCALE_ORDER).toEqual(["en", "zh", "ja", "es", "it"]);
    for (const code of LOCALE_ORDER) {
      expect(LOCALES[code]).toBeDefined();
    }
  });

  it("every locale has exactly the English key set (no missing/stray keys)", () => {
    for (const code of LOCALE_ORDER) {
      const keys = Object.keys(LOCALES[code]).sort();
      expect(keys, `locale ${code} key set`).toEqual(
        [...REQUIRED_KEYS].sort(),
      );
    }
  });

  it("no translation value is empty or whitespace-only", () => {
    for (const code of LOCALE_ORDER) {
      const dict = LOCALES[code] as unknown as Record<string, string>;
      for (const key of REQUIRED_KEYS) {
        expect(dict[key]?.trim().length, `${code}.${String(key)}`).toBeGreaterThan(
          0,
        );
      }
    }
  });

  it("non-English locales actually differ from English on prose keys", () => {
    // Guard against a forgotten copy-paste of English into another locale.
    const proseKeys: (keyof typeof en)[] = [
      "hero_title",
      "hero_subtitle",
      "pricing_title",
    ];
    for (const code of LOCALE_ORDER) {
      if (code === "en") continue;
      for (const key of proseKeys) {
        expect(LOCALES[code][key], `${code}.${String(key)}`).not.toBe(en[key]);
      }
    }
  });
});

describe("locale resolution", () => {
  it("matches on the primary subtag", () => {
    expect(resolveLocale(["ja-JP"])).toBe("ja");
    expect(resolveLocale(["zh-Hans-CN"])).toBe("zh");
    expect(resolveLocale(["es-419"])).toBe("es");
    expect(resolveLocale(["it-IT"])).toBe("it");
  });

  it("falls back to default for unsupported languages", () => {
    expect(resolveLocale(["de-DE", "fr"])).toBe(DEFAULT_LOCALE);
    expect(resolveLocale([])).toBe(DEFAULT_LOCALE);
  });

  it("prefers the first supported candidate", () => {
    expect(resolveLocale(["de", "ja", "en"])).toBe("ja");
  });
});

describe("helpers", () => {
  it("isLocaleCode narrows correctly", () => {
    expect(isLocaleCode("ja")).toBe(true);
    expect(isLocaleCode("xx")).toBe(false);
    expect(isLocaleCode(null)).toBe(false);
  });

  it("getTranslation returns the right dict and falls back", () => {
    expect(getTranslation("ja").locale_name).toBe("日本語");
    // @ts-expect-error testing the runtime fallback for a bad code
    expect(getTranslation("zz")).toBe(LOCALES[DEFAULT_LOCALE]);
  });
});
