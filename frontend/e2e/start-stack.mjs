import { startBackend, startVite } from "./servers.mjs";

const backend = await startBackend();
let frontend;
const close = async () => {
  if (frontend) await frontend.close();
  await backend.close();
  process.exit(0);
};
process.once("SIGTERM", close);
process.once("SIGINT", close);
try {
  frontend = await startVite({ target: backend.origin, port: 4173 });
  console.log(`Synthetic test stack ready at ${frontend.origin}`);
  await new Promise(() => {});
} catch (error) {
  await backend.close();
  throw error;
}
