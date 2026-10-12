/** Real HTTP regression: the frontend origin must route /api before the SPA. */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { startBackend, startVite } from "../e2e/servers.mjs";

const backend = await startBackend();
const modes = process.argv.includes("--dev-only") ? ["dev"] : ["dev", "preview"];
try {
  for (const mode of modes) {
    await test(`POST /api/convert reaches the Python API before SPA fallback (${mode})`, async () => {
      const frontend = await startVite({ mode, target: backend.origin });
      try {
        const form = new FormData();
        form.append("file", new Blob([await readFile(new URL("../../backend/tests/fixtures/acmebank.pdf", import.meta.url))]), "synthetic.pdf");
        form.append("account_id", `routing-${mode}`);
        form.append("fmt", "json");
        const response = await fetch(`${frontend.origin}/api/convert`, { method: "POST", body: form });
        assert.equal(response.status, 200, `conversion returned ${response.status}; /api must reach FastAPI instead of the static frontend`);
        assert.match(response.headers.get("content-type") ?? "", /application\/json/, "the API must return JSON, never the SPA HTML");
        const body = await response.json();
        assert.equal(body.summary.count, 5);
        assert.equal(body.transactions[0].description, "ACH PAYROLL DEPOSIT");
        assert.equal(body.transactions[0].amount, "3250.00");
        assert.deepEqual(body.charge, { metered: false, pages: 1 }, "default missing-key conversion is explicitly unmetered");
        const pricing = await fetch(`${frontend.origin}/api/pricing`);
        assert.equal((await pricing.json()).checkout_available, false);

        // Unknown API routes must also remain API 404s, never success/SPA HTML.
        const missing = await fetch(`${frontend.origin}/api/not-a-route`);
        assert.equal(missing.status, 404);
        assert.match(missing.headers.get("content-type") ?? "", /application\/json/);
      } finally {
        await frontend.close();
      }
    });
  }
} finally {
  await backend.close();
}
