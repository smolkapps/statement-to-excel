import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const canonicalUrl = "https://statement-to-excel.apps.smolkin.org/";

const html = readFileSync(`${frontendRoot}/index.html`, "utf8");
const robots = readFileSync(`${frontendRoot}/public/robots.txt`, "utf8");
const sitemap = readFileSync(`${frontendRoot}/public/sitemap.xml`, "utf8");

assert.match(html, /<title>[^<]*Bank Statement PDF to Excel[^<]*<\/title>/);
assert.match(html, /<meta\s+name="description"\s+content="[^"]+"\s*\/>/);
assert.equal(
  [...html.matchAll(/<link\s+rel="canonical"\s+href="([^"]+)"\s*\/>/g)]
    .map((match) => match[1])
    .join(","),
  canonicalUrl,
  "index.html must contain exactly one canonical URL for the live app",
);
assert.match(html, /<script type="application\/ld\+json">[\s\S]*WebApplication/);
assert.match(robots, new RegExp(`Sitemap: ${canonicalUrl}sitemap\\.xml`));
assert.match(sitemap, new RegExp(`<loc>${canonicalUrl}<\\/loc>`));

console.log("SEO contract verified: canonical, metadata, robots, and sitemap");
