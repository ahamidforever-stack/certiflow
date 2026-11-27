// Browser walkthrough of the review flow (Phase 4). Run:  cd web && npx playwright test
// Starts its own server (e2e/server.sh): mock LLM, sample assets, throw-away data. Never touches ./dev.sh.
import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";

const port = Number(process.env.E2E_PORT || 8765);
process.env.E2E_DIR ||= join(tmpdir(), "certiflow-e2e");
process.env.E2E_PORT = String(port);

export default defineConfig({
  testDir: "e2e",
  timeout: 240_000,
  expect: { timeout: 60_000 },
  workers: 1,
  reporter: [["list"]],
  outputDir: join(process.env.E2E_DIR, "results"),
  use: { baseURL: `http://127.0.0.1:${port}`, viewport: { width: 1440, height: 900 }, trace: "retain-on-failure" },
  webServer: {
    command: "bash e2e/server.sh",
    url: `http://127.0.0.1:${port}/api/health`,
    timeout: 180_000,
    reuseExistingServer: false,
    env: { E2E_DIR: process.env.E2E_DIR, E2E_PORT: String(port) },
  },
});
