import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";
// @ts-expect-error Plain Node server helper supplies the backend Python.
import { python } from "./servers.mjs";

const statement = resolve("../work/e2e-fixtures/unmetered-ten-page.pdf");

test.beforeAll(() => {
  const generated = spawnSync(python, ["-c", `
from pathlib import Path
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
target = Path('../work/e2e-fixtures/unmetered-ten-page.pdf')
target.parent.mkdir(parents=True, exist_ok=True)
c = canvas.Canvas(str(target), pagesize=LETTER, invariant=1)
for page in range(1, 11):
    c.drawString(40, 750, 'Synthetic statement - January 2024')
    c.drawString(40, 730, 'Account ending 0000')
    c.drawString(40, 710, 'Date Description Amount Balance')
    c.drawString(40, 690, f'01/{page:02d}/2024 SYNTHETIC PAYROLL {page} 100.00 {page * 100:.2f}')
    c.showPage()
c.save()
`], { cwd: resolve("../backend"), encoding: "utf8" });
  expect(generated.status, generated.stderr).toBe(0);
});

test("missing Stripe keys hide all billing UI and allow repeated ten-page downloads without account requests or quota", async ({ page }) => {
  await page.route("https://umami.smolkin.org/**", (route) => route.abort());
  const requests: string[] = [];
  page.on("request", (request) => requests.push(new URL(request.url()).pathname));
  const pricingPromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/pricing");
  await page.goto("/?checkout=success&session_id=cs_test_unconfigured_return");
  const pricing = await pricingPromise;
  expect(pricing.status()).toBe(200);
  expect((await pricing.json()).checkout_available).toBe(false);
  await expect(page.locator("#pricing")).toHaveCount(0);
  await expect(page.locator('a[href="#pricing"]')).toHaveCount(0);
  await expect(page.locator(".account-chip")).toHaveCount(0);
  for (const locale of ["en", "zh", "ja", "es", "it"]) {
    await page.getByLabel("Select language").selectOption(locale);
    await expect(page.locator("#pricing")).toHaveCount(0);
    await expect(page.locator('a[href="#pricing"]')).toHaveCount(0);
    await expect(page.locator(".account-chip")).toHaveCount(0);
  }
  await page.getByLabel("Select language").selectOption("en");
  await page.getByLabel("Output format").selectOption("json");

  for (let attempt = 0; attempt < 2; attempt++) {
    // A new selection creates a distinct File/request, so this exercises the
    // server twice rather than reusing a prior client conversion result.
    await page.locator('input[type="file"]').setInputFiles(statement);
    const responsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/convert");
    const downloadPromise = page.waitForEvent("download");
    await page.locator(".convert-controls").getByRole("button", { name: "Convert", exact: true }).click();
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result.charge).toEqual({ metered: false, pages: 10 });
    expect(result.summary.count).toBe(10);
    expect(result.transactions).toHaveLength(10);
    await expect(page.locator(".results tbody tr")).toHaveCount(10);
    expect((await downloadPromise).suggestedFilename()).toBe("statement.json");
    await expect(page.getByRole("alert")).toHaveCount(0);
  }

  // Focus and checkout-return parameters must not activate billing polling.
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.locator(".account-chip")).toHaveCount(0);
  expect(requests.filter((path) => path === "/api/convert")).toHaveLength(2);
  expect(requests.filter((path) => path.startsWith("/api/account") || path.startsWith("/api/checkout"))).toEqual([]);
});
