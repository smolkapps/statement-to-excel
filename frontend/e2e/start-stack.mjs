import { startBackend, startVite } from "./servers.mjs";

const analyticsTest = process.argv.includes("--analytics");
const checkoutConfigured = process.argv.includes("--configured");
const port = Number(process.argv.find((argument) => argument.startsWith("--port="))?.slice("--port=".length) ?? "4173");
const backend = await startBackend({ checkoutConfigured });
let frontend;
const close = async () => {
  if (frontend) await frontend.close();
  await backend.close();
  process.exit(0);
};
process.once("SIGTERM", close);
process.once("SIGINT", close);
try {
  frontend = await startVite({ target: backend.origin, port, analyticsTest, mode: analyticsTest ? "dev" : "preview" });
  console.log(`Synthetic test stack ready at ${frontend.origin}`);
  await new Promise(() => {});
} catch (error) {
  await backend.close();
  throw error;
}
