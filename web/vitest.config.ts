import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    css: false,
    restoreMocks: true,
    // Interaction-heavy screen tests (typed forms) exceed the 5 s default on slow or busy hosts.
    testTimeout: 20000,
    // Coverage (G-25): `pnpm test:coverage` measures the application sources; CI enforces the
    // thresholds below (set under the baseline measured on 2026-09-12 so regressions fail the
    // job while ordinary churn does not).
    coverage: {
      provider: "v8",
      reporter: ["text-summary", "lcov"],
      reportsDirectory: "./coverage",
      include: ["src/**/*.{ts,tsx}"],
      // main.tsx and pwa.ts only run in a real browser (service-worker registration is guarded by
      // import.meta.env.PROD); the v8 provider cannot remap untransformed TypeScript it never saw.
      exclude: [
        "src/**/*.test.{ts,tsx}",
        "src/**/*.d.ts",
        "src/main.tsx",
        "src/pwa.ts",
        "src/vite-env.d.ts",
      ],
      // Baseline 2026-09-12 (23 files, 49 tests): statements 54.3 %, branches 42.1 %,
      // functions 41.4 %, lines 56.8 %. Gates sit a few points below so regressions fail the job.
      thresholds: { lines: 52, statements: 50, functions: 37, branches: 38 },
    },
  },
});
