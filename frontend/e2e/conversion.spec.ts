import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";
// @ts-expect-error Plain Node server helper also supplies the backend Python.
import { python } from "./servers.mjs";

const fixture = (name: string) => resolve("../backend/tests/fixtures", name);
const edgeFixture = (name: string) => resolve("../work/e2e-fixtures", name);

test.beforeAll(() => {
  // Reuse synthetic drawing helpers only; do not import the API or customer PDFs.
  const generated = spawnSync(python, ["-c", `
from pathlib import Path
from reportlab.lib.pdfencrypt import StandardEncryption
from tests.test_pdf_edges import _pdf, _text_page
from tests.accuracy_harness import CARD_LAYOUTS, LAYOUTS, render
directory = Path('../work/e2e-fixtures')
directory.mkdir(parents=True, exist_ok=True)
(directory / 'protected.pdf').write_bytes(_pdf(_text_page, encrypt=StandardEncryption('synthetic-fixture-password')).getvalue())
def multiple(c):
    _text_page(c, account='xxxx1111')
    c.showPage()
    _text_page(c, account='xxxx2222')
(directory / 'multiple-accounts.pdf').write_bytes(_pdf(multiple).getvalue())
render(next(layout for layout in LAYOUTS if layout.slug == 'wells-fargo'), directory)
render(next(layout for layout in CARD_LAYOUTS if layout.slug == 'capital-one-card'), directory)
from tests.test_reconciliation_api import synthetic_statement
for name, options in [('reconciled', {}), ('off-by-one', {'closing': '111.00'}), ('without-totals', {'totals': False})]:
    (directory / f'{name}.pdf').write_bytes(synthetic_statement(**options))
`], { cwd: resolve("../backend"), encoding: "utf8" });
  expect(generated.status, generated.stderr).toBe(0);
});

async function visit(page: Page) {
  // Use the existing Umami API locally, without sending test activity externally.
  // Serve the stub in the page's script context: Camoufox deliberately isolates
  // addInitScript/evaluate globals from page scripts. DOM attributes let both
  // browsers inspect the same captured events without enabling main-world eval.
  await page.route("https://umami.smolkin.org/**", (route) => route.fulfill({
    contentType: "application/javascript",
    body: `
      const events = [];
      const properties = [];
      const root = document.documentElement;
      root.dataset.testAnalyticsEvents = '[]';
      root.dataset.testAnalyticsProperties = '[]';
      window.umami = { track: (event, data) => {
        if (!event) return;
        events.push(event);
        if (event === 'convert-success') properties.push(data);
        root.dataset.testAnalyticsEvents = JSON.stringify(events);
        root.dataset.testAnalyticsProperties = JSON.stringify(properties);
      } };
    `,
  }));
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-test-analytics-events", "[]");
  // Await the configured capability response before testing metered conversion.
  await expect(page.locator(".account-chip")).toBeVisible();
}

async function analytics(page: Page, kind: "events" | "properties") {
  return JSON.parse((await page.locator("html").getAttribute(`data-test-analytics-${kind}`))!);
}

async function account(page: Page) {
  const id = await page.evaluate(() => localStorage.getItem("stx_account_id"));
  expect(id).toMatch(/^web_/);
  const response = await page.request.post("/api/account", { data: { account_id: id } });
  expect(response.ok()).toBeTruthy();
  return response.json();
}

test("upload → convert → XLSX download uses one request and one page charge even with a rapid double click", async ({ page }, testInfo) => {
  await visit(page);
  const conversionRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/convert") conversionRequests.push(request.url());
  });
  await page.locator('input[type="file"]').setInputFiles(fixture("acmebank.pdf"));
  const downloadPromise = page.waitForEvent("download");
  // Two DOM events in one frame exercise the path React state alone cannot lock.
  await page.locator(".convert-controls").getByRole("button", { name: "Convert", exact: true }).evaluate((button) => {
    (button as HTMLButtonElement).click();
    (button as HTMLButtonElement).click();
  });
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("statement.xlsx");
  const downloadedPath = testInfo.outputPath("synthetic-statement.xlsx");
  await download.saveAs(downloadedPath);
  await expect(page.locator(".results tbody tr")).toHaveCount(5);

  // Inspect the actual downloaded workbook, including every amount and balance.
  const verified = spawnSync(python, ["-c", `
import json, sys
from decimal import Decimal
from openpyxl import load_workbook
expected = json.load(open(sys.argv[2]))
wb = load_workbook(sys.argv[1], data_only=True)
assert wb.sheetnames == ['Transactions', 'Summary', 'Checks']
rows = list(wb['Transactions'].iter_rows(min_row=2, values_only=True))
assert len(rows) == len(expected)
for actual, want in zip(rows, expected):
    assert actual[0].date().isoformat() == want['date']
    assert actual[1] == want['description']
    assert Decimal(str(actual[2])) == Decimal(want['amount'])
    assert (Decimal(str(actual[3])) if actual[3] is not None else None) == (Decimal(want['balance']) if want['balance'] is not None else None)
    assert actual[4] == want['currency']
    assert actual[5] == want['type']
assert wb['Summary']['B2'].value == len(expected)
print(f'{len(rows)} workbook rows verified')
`, downloadedPath, fixture("acmebank.expected.json")], { encoding: "utf8" });
  expect(verified.status, verified.stderr).toBe(0);
  expect(verified.stdout).toContain("5 workbook rows verified");
  // The visible download button reuses the converted bytes, never a second API call.
  const redownloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download", exact: true }).click();
  expect((await redownloadPromise).suggestedFilename()).toBe("statement.xlsx");
  expect(conversionRequests).toHaveLength(1);
  expect((await account(page)).pages_used_this_cycle).toBe(1);
  const events = await analytics(page, "events");
  expect(events).toEqual(["file-selected", "convert-success"]);
  await expect(page.locator(".reconciliation-status")).toContainText("Can't check:");
});

test("an image-only PDF returns an actionable OCR error without a download or page charge", async ({ page }) => {
  await visit(page);
  const downloads: string[] = [];
  page.on("download", (download) => downloads.push(download.suggestedFilename()));
  await page.locator('input[type="file"]').setInputFiles(fixture("scanned_empty.pdf"));
  const responsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/convert");
  await page.locator(".convert-controls").getByRole("button", { name: "Convert", exact: true }).click();
  expect((await responsePromise).status()).toBe(422);
  await expect(page.getByRole("alert")).toContainText(/OCR|text layer|image-only|scanned/i);
  expect(downloads).toHaveLength(0);
  expect((await account(page)).pages_used_this_cycle).toBe(0);
  const events = await analytics(page, "events");
  expect(events).toEqual(["file-selected", "convert-error"]);
});

test("a recoverable conversion timeout shows localized guidance and retries once without a lost charge", async ({ page }) => {
  await visit(page);
  const requestKeys: (string | undefined)[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/convert") requestKeys.push(request.headers()["idempotency-key"]);
  });
  // The real kill/reap/deadline boundary is exercised by backend process tests.
  // Inject only its HTTP response here to verify the browser's recovery path.
  await page.route("**/api/convert", (route) => route.fulfill({
    status: 504, contentType: "application/json",
    body: JSON.stringify({ detail: "Synthetic server timeout; never show raw internal details" }),
  }));
  await page.locator('input[type="file"]').setInputFiles(edgeFixture("reconciled.pdf"));
  await page.getByLabel("Output format").selectOption("json");
  const timedOut = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/convert");
  await page.locator(".convert-controls").getByRole("button", { name: "Convert", exact: true }).click();
  expect((await timedOut).status()).toBe(504);
  await expect(page.getByRole("alert")).toHaveText("Conversion took too long. Please try again with a smaller statement or split it into fewer pages.");
  expect((await account(page)).pages_used_this_cycle).toBe(0);
  await expect(page.locator(".results")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Download", exact: true })).toHaveCount(0);
  const localized = new Set<string>();
  for (const locale of ["en", "zh", "ja", "es", "it"]) {
    // Select the file and receive the error in this locale; the component keeps
    // the safe message shown at failure time until another conversion attempt.
    await page.getByLabel("Select language").selectOption(locale);
    const timeout = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/convert");
    await page.locator(".convert-controls button").click();
    expect((await timeout).status()).toBe(504);
    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible();
    expect(await alert.textContent()).not.toContain("Synthetic server timeout");
    localized.add((await alert.textContent())!);
  }
  expect(localized.size).toBe(5);
  await page.getByLabel("Select language").selectOption("en");
  await page.unroute("**/api/convert");
  const retried = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/convert");
  const downloaded = page.waitForEvent("download");
  await page.locator(".convert-controls").getByRole("button", { name: "Convert", exact: true }).click();
  expect((await retried).status()).toBe(200);
  expect((await downloaded).suggestedFilename()).toBe("statement.json");
  await expect(page.locator(".reconciliation-status")).toHaveAttribute("data-status", "balanced");
  expect((await account(page)).pages_used_this_cycle).toBe(1);
  expect(requestKeys).toHaveLength(7);
  expect(new Set(requestKeys).size).toBe(1);
});

for (const scenario of [
  { filename: "protected.pdf", message: /Password-protected.*Unlock it locally/i },
  { filename: "multiple-accounts.pdf", message: /Multiple accounts.*separately/i },
]) {
  test(`${scenario.filename} is clearly rejected before charging`, async ({ page }) => {
    await visit(page);
    await page.locator('input[type="file"]').setInputFiles(edgeFixture(scenario.filename));
    const responsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/convert");
    await page.locator(".convert-controls").getByRole("button", { name: "Convert", exact: true }).click();
    expect((await responsePromise).status()).toBe(422);
    await expect(page.getByRole("alert")).toContainText(scenario.message);
    expect((await account(page)).pages_used_this_cycle).toBe(0);
  });
}

test("a two-page statement preserves every ground-truth row and charges two pages once", async ({ page }) => {
  await visit(page);
  await page.locator('input[type="file"]').setInputFiles(edgeFixture("wells-fargo.pdf"));
  await page.getByLabel("Output format").selectOption("json");
  const downloadPromise = page.waitForEvent("download");
  const responsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/convert");
  await page.locator(".convert-controls").getByRole("button", { name: "Convert", exact: true }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const result = await response.json();
  const truth = JSON.parse(readFileSync(edgeFixture("wells-fargo.expected.json"), "utf8"));
  // The shared accuracy harness compares money with Decimal, so 0 and 0.00
  // have equal exact value while every other field and row order must match.
  const measured = spawnSync(python, ["-c", `
import json, sys
from tests.accuracy_harness import measure
result = measure(json.load(open(sys.argv[1])), json.load(sys.stdin))
assert result['accuracy'] == 1, result
`, edgeFixture("wells-fargo.expected.json")], {
    cwd: resolve("../backend"),
    input: JSON.stringify(result.transactions),
    encoding: "utf8",
  });
  expect(measured.status, measured.stderr).toBe(0);
  await expect(page.locator(".results tbody tr")).toHaveCount(truth.length);
  expect((await downloadPromise).suggestedFilename()).toBe("statement.json");
  expect((await account(page)).pages_used_this_cycle).toBe(2);
});

test("a failed configured checkout rejects a double click and retries its intent without granting Pro", async ({ page }) => {
  // Test the UI retry contract without making any request to Stripe. Provider
  // failures and durable idempotency are exercised in the Python API suite.
  await page.route("**/api/checkout", (route) => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ detail: "Synthetic provider outage" }),
  }));
  await visit(page);
  const keys: (string | undefined)[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/checkout") keys.push(request.headers()["idempotency-key"]);
  });
  const choose = page.locator(".plan-card").filter({ has: page.getByRole("heading", { name: "Starter", exact: true }) })
    .getByRole("button", { name: "Choose plan", exact: true });
  const failed = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/checkout");
  await choose.evaluate((button) => {
    (button as HTMLButtonElement).click();
    (button as HTMLButtonElement).click();
  });
  expect((await failed).status()).toBe(503);
  await expect(page.getByRole("alert")).toHaveText("Checkout could not be opened. Please try again.");
  expect(keys).toHaveLength(1);
  await expect(choose).toBeEnabled();
  const retried = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/checkout");
  await choose.click();
  expect((await retried).status()).toBe(503);
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBeTruthy();
  expect(keys[1]).toBe(keys[0]);
  expect(await account(page)).toMatchObject({ plan: "free", pro: false, credits: 0, pages_used_this_cycle: 0 });
  const events = await analytics(page, "events");
  expect(events).toEqual(["upgrade-click", "upgrade-click"]);
});

for (const scenario of [
  { filename: "reconciled.pdf", status: "balanced", balanced: "yes", english: "Balanced:", flags: false },
  { filename: "off-by-one.pdf", status: "not_balanced", balanced: "no", english: "Doesn't balance:", flags: true },
  { filename: "without-totals.pdf", status: "cannot_check", balanced: "unknown", english: "Can't check:", flags: false },
]) {
  test(`${scenario.status} shows printed-evidence status in every locale with restricted analytics`, async ({ page }) => {
    await visit(page);
    await page.getByLabel("Output format").selectOption("json");
    await page.locator('input[type="file"]').setInputFiles(edgeFixture(scenario.filename));
    const responsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/convert");
    const downloadPromise = page.waitForEvent("download");
    await page.locator(".convert-controls").getByRole("button", { name: "Convert", exact: true }).click();
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    expect((await response.json()).reconciliation.status).toBe(scenario.status);
    expect((await downloadPromise).suggestedFilename()).toBe("statement.json");
    const line = page.locator(".reconciliation-status");
    await expect(line).toContainText(scenario.english);
    if (scenario.status === "balanced") await expect(line).toContainText("$110.00");
    if (scenario.status === "not_balanced") await expect(line).toContainText("$1.00");
    const translations = new Set<string>();
    for (const locale of ["en", "zh", "ja", "es", "it"]) {
      await page.getByLabel("Select language").selectOption(locale);
      await expect(line).toBeVisible();
      translations.add((await line.textContent())!);
      await expect(page.locator(".results tbody tr.flagged-row")).toHaveCount(scenario.flags ? 2 : 0);
    }
    expect(translations.size).toBe(5);
    const properties = await analytics(page, "properties");
    expect(properties).toEqual([{ balanced: scenario.balanced, layout: "deposit_lines" }]);
  });
}

test("credit-card preview uses the card equation and downloaded Checks formulas", async ({ page }, testInfo) => {
  await visit(page);
  await page.locator('input[type="file"]').setInputFiles(edgeFixture("capital-one-card.pdf"));
  const responsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/convert");
  const downloadPromise = page.waitForEvent("download");
  await page.locator(".convert-controls").getByRole("button", { name: "Convert", exact: true }).click();
  const result = await (await responsePromise).json();
  expect(result.reconciliation).toMatchObject({ status: "balanced", account_type: "card" });
  await expect(page.locator(".reconciliation-status")).toContainText("Balanced: previous");
  await expect(page.locator(".reconciliation-status")).toContainText("payments and credits");
  const path = testInfo.outputPath("synthetic-card.xlsx");
  await (await downloadPromise).saveAs(path);
  const checked = spawnSync(python, ["-c", `
import sys
from openpyxl import load_workbook
workbook = load_workbook(sys.argv[1])
assert workbook['Checks']['B9'].data_type == 'f'
assert workbook['Checks']['B9'].value == '=IF(ISNUMBER(C4),B4-B5+B6+B7+B8,"")'
assert workbook['Checks']['B3'].value == 'balanced'
`, path], { encoding: "utf8" });
  expect(checked.status, checked.stderr).toBe(0);
  expect((await account(page)).pages_used_this_cycle).toBe(1);
  const properties = await analytics(page, "properties");
  expect(properties).toEqual([{ balanced: "yes", layout: "card_lines" }]);
});

test('owned hosted payment management uses private account body and a recoverable failure', async ({ page }) => {
  await page.route('**/api/account', route => route.fulfill({ json: {
    id: route.request().postDataJSON().account_id, plan: 'starter', credits: 50,
    included_pages: 120, pages_used_this_cycle: 2, included_remaining: 118, pro: true,
    management_available: true, billing_hold: false,
  } }));
  const bodies: object[] = [];
  let fail = true;
  await page.route('**/api/billing/portal', route => {
    bodies.push(route.request().postDataJSON());
    return route.fulfill(fail ? { status: 503, json: { detail: 'Synthetic provider unavailable' } } : { json: { portal_url: 'https://billing.stripe.com/synthetic-management' } });
  });
  await page.route('https://billing.stripe.com/**', route => route.fulfill({ contentType: 'text/html', body: '<h1>Synthetic hosted management</h1>' }));
  await visit(page);
  const manage = page.getByRole('button', { name: 'Manage subscription and payment method' });
  await manage.click();
  await expect(page.getByRole('alert')).toHaveText('Checkout could not be opened. Please try again.');
  fail = false;
  await manage.click();
  await expect(page.getByRole('heading', { name: 'Synthetic hosted management' })).toBeVisible();
  expect(bodies).toHaveLength(2);
  expect(Object.keys(bodies[0])).toEqual(['account_id']);
  expect(bodies[0]).toEqual(bodies[1]);
});

test('a payment-reconciliation hold gives localized guidance without charges or a download', async ({ page }) => {
  await visit(page);
  await page.route('**/api/convert', route => route.fulfill({ status: 409, json: { error: 'billing_hold', detail: 'Synthetic private provider detail' } }));
  await page.locator('input[type=file]').setInputFiles(edgeFixture('reconciled.pdf'));
  const messages = new Set<string>(); const downloads: string[] = [];
  page.on('download', d => downloads.push(d.suggestedFilename()));
  for (const locale of ['en', 'zh', 'ja', 'es', 'it']) {
    await page.getByLabel('Select language').selectOption(locale);
    const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/convert');
    await page.locator('.convert-controls button').click();
    expect((await response).status()).toBe(409);
    const alert = page.getByRole('alert'); await expect(alert).toBeVisible();
    messages.add(await alert.innerText());
    expect(await alert.innerText()).not.toContain('Synthetic private provider detail');
  }
  expect(messages.size).toBe(5); expect(downloads).toEqual([]);
  expect((await account(page)).pages_used_this_cycle).toBe(0);
});
