import { defineConfig, devices } from "@playwright/test";

/**
 * Browser and accessibility suite (docs/11 s.2 "End-to-end" + "Accessibility"; s.8). Runs against
 * an already running stack (Compose `agni-dev`, seeded with `seed_demo`) - it never starts or
 * resets services. Point BASE_URL below at another stack when needed (the Compose default is
 * the published web port on the loopback address).
 */
const BASE_URL = "http://127.0.0.1:5173";
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  outputDir: "test-results",
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    ...devices["Desktop Chrome"],
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
