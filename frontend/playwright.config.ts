import { existsSync } from "node:fs";
import { defineConfig } from "@playwright/test";

const executablePath = process.env.STX_CHROMIUM_PATH ||
  (existsSync("/usr/bin/chromium") ? "/usr/bin/chromium" : undefined);

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  outputDir: "../work/playwright-results",
  use: {
    baseURL: "http://127.0.0.1:4173",
    browserName: "chromium",
    headless: true,
    locale: "en-US",
    launchOptions: { executablePath },
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "configured-billing",
      testMatch: "conversion.spec.ts",
      use: { baseURL: "http://127.0.0.1:4174" },
    },
    {
      name: "unconfigured-billing",
      testMatch: "availability.spec.ts",
      use: { baseURL: "http://127.0.0.1:4173" },
    },
  ],
  webServer: [
    {
      command: "node e2e/start-stack.mjs --port=4173",
      url: "http://127.0.0.1:4173/api/health",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "node e2e/start-stack.mjs --configured --port=4174",
      url: "http://127.0.0.1:4174/api/health",
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
