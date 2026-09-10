import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers";
import { HomePage } from "./HomePage";

function renderHome() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <AppProviders client={client}>
      <HomePage />
    </AppProviders>,
  );
}

function stubFetch(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HomePage API readiness", () => {
  it("shows loading, then ready with each check", async () => {
    stubFetch(200, {
      status: "ready",
      checks: { database: "pass", schema: "pass", configuration: "pass" },
      service_mode: "DEMO",
    });
    renderHome();

    const region = screen.getByTestId("api-readiness");
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(region).toHaveAttribute("data-state", "loading");
    expect(screen.getByText("Checking the API...")).toBeInTheDocument();

    expect(await screen.findByText("API is ready")).toBeInTheDocument();
    expect(region).toHaveAttribute("data-state", "ready");
    expect(screen.getByText("Database")).toBeInTheDocument();
    expect(screen.getByText("Schema")).toBeInTheDocument();
    expect(screen.getByText("Configuration")).toBeInTheDocument();
    expect(screen.getByText("DEMO")).toBeInTheDocument();
  });

  it("shows not ready and the failing checks on 503", async () => {
    stubFetch(503, {
      status: "not_ready",
      checks: { database: "fail", schema: "fail", configuration: "pass" },
      service_mode: "DEMO",
    });
    renderHome();

    expect(await screen.findByText("API is not ready")).toBeInTheDocument();
    expect(screen.getByTestId("api-readiness")).toHaveAttribute("data-state", "not_ready");
    expect(screen.getAllByText(/fail/)).toHaveLength(2);
    expect(screen.getAllByText(/pass/)).toHaveLength(1);
  });

  it("shows an error state when the API cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    renderHome();

    expect(await screen.findByText("The API could not be reached")).toBeInTheDocument();
    expect(screen.getByTestId("api-readiness")).toHaveAttribute("data-state", "error");
  });
});
