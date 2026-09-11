import "fake-indexeddb/auto";
import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

// findBy*/waitFor default to 1 s; on a busy host (parallel workers, IndexedDB open, fetch
// stubs) the first render can take longer, which produced the F-01 flake in
// InspectionDetailPage.test.tsx. Assertions still fail fast on a real regression.
configure({ asyncUtilTimeout: 5000 });

afterEach(() => {
  cleanup();
});
