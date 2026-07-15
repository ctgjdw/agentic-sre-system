import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  use: { baseURL: process.env.UI_BASE ?? "http://localhost:8088" },
  timeout: 120_000,
  reporter: [["list"]],
});
