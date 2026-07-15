/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8080" } },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    globals: true,
    // Playwright specs live under e2e/ and use a different runner; keep vitest out.
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
  },
});
