import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";
// @ts-expect-error Plain Node server helper supplies the backend Python.
import { python } from "./servers.mjs";

const fixture = (name: string) => resolve("../work/e2e-fixtures", name);

test.beforeAll(() => {
  const generated = spawnSync(python, ["-c", `
from pathlib import Path
from tests.accuracy_harness import CARD_LAYOUTS, render
from tests.test_reconciliation_api import synthetic_statement
directory = Path('../work/e2e-fixtures')
directory.mkdir(parents=True, exist_ok=True)
render(next(layout for layout in CARD_LAYOUTS if layout.slug == 'capital-one-card'), directory)
for name, options in [('reconciled', {}), ('off-by-one', {'closing': '111.00'}), ('without-totals', {'totals': False})]:
    (directory / f'{name}.pdf').write_bytes(synthetic_statement(**options))
`], { cwd: resolve("../backend"), encoding: "utf8" });
  expect(generated.status, generated.stderr).toBe(0);
});

for (const viewport of [{ width: 1365, height: 900 }, { width: 390, height: 844 }]) {
  test(`${viewport.width}x${viewport.height} conversion, reconciliation and download journeys stay usable`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    // Test only the local stack; never send synthetic conversion activity to
    // production analytics or load a personal browser profile.
    await page.route("https://umami.smolkin.org/**", (route) => route.fulfill({
      contentType: "application/javascript", body: "",
    }));
    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];
    const failedLocalRequests: string[] = [];
    const localResponses: { path: string; status: number }[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("requestfailed", (request) => {
      if (new URL(request.url()).hostname === "127.0.0.1") failedLocalRequests.push(request.url());
    });
    page.on("response", (response) => {
      const url = new URL(response.url());
      if (url.hostname === "127.0.0.1" && url.pathname.startsWith("/api/")) {
        localResponses.push({ path: url.pathname, status: response.status() });
      }
    });
    await page.goto("/");
    await expect(page.locator("#pricing")).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath("upload.png"), fullPage: true });

    const scenarios = [
      { file: "reconciled.pdf", format: "xlsx", status: "balanced", rows: 2 },
      { file: "capital-one-card.pdf", format: "xlsx", status: "balanced", rows: 8 },
      { file: "without-totals.pdf", format: "json", status: "cannot_check", rows: 2 },
      { file: "off-by-one.pdf", format: "csv", status: "not_balanced", rows: 2 },
    ];
    for (const scenario of scenarios) {
      await page.locator('input[type="file"]').setInputFiles(fixture(scenario.file));
      await page.getByLabel("Output format").selectOption(scenario.format);
      const responsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/convert");
      const downloadPromise = page.waitForEvent("download");
      await page.locator(".convert-controls").getByRole("button", { name: "Convert", exact: true }).click();
      const response = await responsePromise;
      expect(response.status()).toBe(200);
      const result = await response.json();
      expect(result.reconciliation.status).toBe(scenario.status);
      expect(result.charge).toEqual({ metered: false, pages: 1 });
      expect(result.transactions).toHaveLength(scenario.rows);
      await expect(page.locator(".reconciliation-status")).toHaveAttribute("data-status", scenario.status);
      await expect(page.locator(".results tbody tr")).toHaveCount(scenario.rows);
      await expect(page.locator(".results tbody tr.flagged-row")).toHaveCount(scenario.status === "not_balanced" ? 2 : 0);
      const download = await downloadPromise;
      expect(download.suggestedFilename()).toBe(`statement.${scenario.format}`);
      const saved = testInfo.outputPath(`${scenario.file}.${scenario.format}`);
      await download.saveAs(saved);
      if (scenario.format === "xlsx") {
        const checked = spawnSync(python, ["-c", `
import json, sys
from decimal import Decimal
from openpyxl import load_workbook
workbook = load_workbook(sys.argv[1])
cached = load_workbook(sys.argv[1], data_only=True)
assert workbook.sheetnames == ['Transactions', 'Summary', 'Checks']
actual = list(workbook['Transactions'].iter_rows(min_row=2, values_only=True))
if sys.argv[2] == 'card':
    expected = json.load(open(sys.argv[3]))
    assert len(actual) == len(expected)
    for row, want in zip(actual, expected):
        assert row[0].date().isoformat() == want['date']
        assert row[1] == want['description']
        assert Decimal(str(row[2])) == Decimal(want['amount'])
        assert (Decimal(str(row[3])) if row[3] is not None else None) == (Decimal(want['balance']) if want['balance'] is not None else None)
    closing = 'B9'
    assert workbook['Checks'][closing].value == '=IF(ISNUMBER(C4),B4-B5+B6+B7+B8,"")'
else:
    assert [(row[0].date().isoformat(), row[2], row[3]) for row in actual] == [('2023-12-31', 20, 120), ('2024-01-02', -10, 110)]
    closing = 'B7'
    assert workbook['Checks'][closing].value == '=IF(ISNUMBER(C4),B4+B5-B6,"")'
assert workbook['Checks'][closing].data_type == 'f'
assert workbook['Checks']['B3'].value == 'balanced'
assert workbook['Checks'][closing.replace('B', 'C')].value is not None
# openpyxl stores formulas but does not calculate them. A blank cache is not
# evidence of a recalculated result; independent formula evaluation is separate.
assert cached['Checks'][closing].value is None
assert workbook.calculation.fullCalcOnLoad
print(f'{len(actual)} downloaded transaction rows and stored Checks formulas verified; no calculated cache')
`, saved, scenario.file.includes("card") ? "card" : "deposit", fixture("capital-one-card.expected.json")], { encoding: "utf8" });
        expect(checked.status, checked.stderr).toBe(0);
      } else if (scenario.format === "csv") {
        const csv = readFileSync(saved, "utf8");
        expect(csv.split("\n")[0]).toBe("date,description,amount,balance,currency,type");
        expect(csv).toContain("2024-01-02,SYNTHETIC PURCHASE,-10.00,110.00,USD,debit");
      } else {
        expect(JSON.parse(readFileSync(saved, "utf8")).reconciliation.status).toBe("cannot_check");
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.locator(".reconciliation-status").scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath(`${scenario.file}.png`), fullPage: true });
      await page.screenshot({ path: testInfo.outputPath(`${scenario.file}.viewport.png`) });
    }

    await page.locator('input[type="file"]').setInputFiles(resolve("../backend/tests/fixtures/scanned_empty.pdf"));
    const failed = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/convert");
    await page.locator(".convert-controls").getByRole("button", { name: "Convert", exact: true }).click();
    expect((await failed).status()).toBe(422);
    await expect(page.getByRole("alert")).toContainText(/OCR|text layer|image-only|scanned/i);
    await expect(page.locator(".results")).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("unsupported.png"), fullPage: true });
    expect(pageErrors).toEqual([]);
    expect(failedLocalRequests).toEqual([]);
    // Chromium logs an expected HTTP error for the deliberately unsupported
    // file. Unexpected script/runtime/network failures remain test failures.
    expect(consoleErrors.filter((message) => !message.includes("422 (Unprocessable Entity)"))).toEqual([]);
    expect(localResponses.filter(({ status }) => status >= 400)).toEqual([{ path: "/api/convert", status: 422 }]);
    await testInfo.attach("local-browser-checks.json", {
      body: JSON.stringify({ viewport, pageErrors, consoleErrors, failedLocalRequests, localResponses }, null, 2),
      contentType: "application/json",
    });
  });
}
