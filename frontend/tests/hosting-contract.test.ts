import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { LOCALES } from "../src/i18n";

describe("hosted converter disclosure", () => {
  const serverTerms = {
    en: /uploaded to our server/i,
    zh: /上传到我们的服务器/,
    ja: /サーバーにアップロード/,
    es: /se sube a nuestro servidor/i,
    it: /caricato sul nostro server/i,
  };
  for (const code of ["en", "zh", "ja", "es", "it"] as const) {
    it(`${code} explains that the PDF leaves the browser for conversion`, () => {
      expect(LOCALES[code].hero_trust).toMatch(serverTerms[code]);
    });
  }
  it("does not promise browser-only processing or absolute non-retention", () => {
    const en = LOCALES.en;
    expect([en.hero_trust, en.feature_private_title, en.feature_private_body].join(" "))
      .not.toMatch(/processed locally|no data is stored|never leaves your/i);
    expect(en.feature_private_body).toContain("without sending your statement to a third-party AI API");
  });
});

describe("existing hosting assets are source managed", () => {
  const html = readFileSync("index.html", "utf8");
  const deployedIconHashes = {
    "favicon.svg": "c6ffa1b2e8fbc5c81195ca129c88f52b8f55882287a79ee6415607d8077270f9",
    "favicon.ico": "4ee27e2f898b34939cc10217666db48e02f90b388a1fc91722152c7ed382975f",
    "apple-touch-icon.png": "349c327a61ed2c361fb9bf962bc58f201018a9adcb3e4ee0e028bc4c48479502",
  };
  for (const [name, hash] of Object.entries(deployedIconHashes)) {
    it(`${name} retains the actual deployed asset and a resolvable index reference`, () => {
      expect(createHash("sha256").update(readFileSync(`public/${name}`)).digest("hex"))
        .toBe(hash);
      expect(html).toContain(`href="/${name}"`);
    });
  }
  it("retains one existing analytics script so the poller does not inject another", () => {
    expect([...html.matchAll(/src="https:\/\/umami\.smolkin\.org\/script\.js"/g)])
      .toHaveLength(1);
    expect(html).toContain('data-website-id="0ee0e19b-b29b-4c98-b3f6-a92a43b4ba5a"');
  });
});
