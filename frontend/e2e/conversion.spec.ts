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
from tests.accuracy_harness import LAYOUTS, render
directory = Path('../work/e2e-fixtures')
directory.mkdir(parents=True, exist_ok=True)
(directory / 'protected.pdf').write_bytes(_pdf(_text_page, encrypt=StandardEncryption('synthetic-fixture-password')).getvalue())
def multiple(c):
    _text_page(c, account='xxxx1111')
    c.showPage()
    _text_page(c, account='xxxx2222')
(directory / 'multiple-accounts.pdf').write_bytes(_pdf(multiple).getvalue())
render(next(layout for layout in LAYOUTS if layout.slug == 'wells-fargo'), directory)
`], { cwd: resolve("../backend"), encoding: "utf8" });
  expect(generated.status, generated.stderr).toBe(0);
});

async function visit(page: Page) {
  // Use the existing Umami API locally, without sending test activity externally.
  await page.route("https://umami.smolkin.org/**", (route) => route.abort());
  await page.addInitScript(() => {
    const events: string[] = [];
    Object.defineProperty(window, "testAnalyticsEvents", { value: events });
    Object.defineProperty(window, "umami", { value: { track: (event: string) => events.push(event) } });
  });
  await page.goto("/");
  // Await the configured capability response before testing metered conversion.
  await expect(page.locator(".account-chip")).toBeVisible();
}

async function account(page: Page) {
  const id = await page.evaluate(() => localStorage.getItem("stx_account_id"));
  expect(id).toMatch(/^web_/);
  const response = await page.request.get(`/api/account/${id}`);
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
assert wb.sheetnames == ['Transactions', 'Summary']
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
  const events = await page.evaluate(() => (window as unknown as { testAnalyticsEvents: string[] }).testAnalyticsEvents);
  expect(events).toEqual(["file-selected", "convert-success"]);
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
  const events = await page.evaluate(() => (window as unknown as { testAnalyticsEvents: string[] }).testAnalyticsEvents);
  expect(events).toEqual(["file-selected", "convert-error"]);
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
  const events = await page.evaluate(() => (window as unknown as { testAnalyticsEvents: string[] }).testAnalyticsEvents);
  expect(events).toEqual(["upgrade-click", "upgrade-click"]);
});
