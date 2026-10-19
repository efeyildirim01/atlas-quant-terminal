import { defineConfig } from "@playwright/test";

// Expects the API (with fixture data ingested) on :8000 and the web app on :3000.
// CI starts both (see .github/workflows/ci.yml). Locally: PW_CHANNEL=msedge uses the installed Edge.
export default defineConfig({
  testDir: "./e2e",
  // Outside the app directory so the dev-server file watcher never sees trace writes.
  outputDir: "../../.artifacts/playwright",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  // Serial: against `next dev`, parallel first visits race on-demand route compilation.
  workers: 1,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    channel: process.env.PW_CHANNEL || undefined,
    viewport: { width: 1600, height: 1000 },
    trace: "retain-on-failure",
  },
});
