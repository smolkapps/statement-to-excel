import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const backendRoot = resolve(frontendRoot, "../backend");
export const python = process.env.STX_PYTHON ?? (existsSync(resolve(backendRoot, ".venv/bin/python")) ? resolve(backendRoot, ".venv/bin/python") : "python");

async function freePort() {
  const server = createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const port = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return port;
}

async function launch(command, args, { cwd, env, port, readyPath = "/" }) {
  const child = spawn(command, args, { cwd, env: { ...process.env, ...env }, stdio: ["ignore", "pipe", "pipe"] });
  let logs = "";
  child.stdout.on("data", (data) => { logs = (logs + data).slice(-8000); });
  child.stderr.on("data", (data) => { logs = (logs + data).slice(-8000); });
  let failure;
  child.once("error", (error) => { failure = error; });
  const origin = `http://127.0.0.1:${port}`;
  const close = async () => {
    if (child.exitCode !== null || child.signalCode !== null) return;
    await new Promise((resolve) => {
      const timer = setTimeout(() => child.kill("SIGKILL"), 3000);
      child.once("exit", () => { clearTimeout(timer); resolve(); });
      child.kill("SIGTERM");
    });
  };
  try {
    for (let attempt = 0; attempt < 150; attempt++) {
      if (failure || child.exitCode !== null) throw failure ?? new Error(`Server exited: ${logs}`);
      try {
        const response = await fetch(`${origin}${readyPath}`, { signal: AbortSignal.timeout(1000) });
        if (response.ok) return { origin, close };
      } catch { /* retry during startup */ }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    throw new Error(`Server did not become ready: ${logs}`);
  } catch (error) {
    await close();
    throw error;
  }
}

export async function startBackend({ checkoutConfigured = false } = {}) {
  const port = await freePort();
  const directory = await mkdtemp(resolve(tmpdir(), "stx-e2e-"));
  try {
    const server = await launch(python, ["-m", "uvicorn", "statement_to_excel.api:app", "--host", "127.0.0.1", "--port", String(port)], {
      cwd: backendRoot,
      // Synthetic prefixes enable the metered UI contract only. They are not
      // Stripe credentials; browser checkout requests are intercepted in tests.
      env: {
        STX_BILLING_PROVIDER: "stripe",
        STX_BILLING_DATABASE: resolve(directory, "billing.sqlite3"),
        STX_STRIPE_SECRET_KEY: checkoutConfigured ? "sk_test_SYNTHETIC_BROWSER_NOT_A_STRIPE_KEY" : "",
        STX_STRIPE_WEBHOOK_SECRET: checkoutConfigured ? "whsec_SYNTHETIC_BROWSER_NOT_A_STRIPE_SECRET" : "",
        STX_CHECKOUT_ORIGIN: "http://127.0.0.1:4174",
      },
      port,
      readyPath: "/api/health",
    });
    return { ...server, close: async () => { await server.close(); await rm(directory, { recursive: true, force: true }); } };
  } catch (error) {
    await rm(directory, { recursive: true, force: true });
    throw error;
  }
}

export async function startVite({ mode = "preview", target, port: requestedPort }) {
  const port = requestedPort ?? await freePort();
  const args = [resolve(frontendRoot, "node_modules/vite/bin/vite.js")];
  if (mode === "preview") args.push("preview");
  args.push("--host", "127.0.0.1", "--port", String(port), "--strictPort");
  return launch(process.execPath, args, { cwd: frontendRoot, env: { STX_API_TARGET: target }, port });
}
