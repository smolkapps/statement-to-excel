/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Local development/preview must use the same /api routing contract as the
// production reverse proxy. Keep the /api prefix: FastAPI routes include it.
const apiProxy = {
  "/api": {
    target: process.env.STX_API_TARGET || "http://127.0.0.1:8000",
    changeOrigin: true,
  },
};

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
  },
});
