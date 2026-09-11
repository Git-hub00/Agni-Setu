import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers";
import { routes } from "../../app/router";

const ACTIVE = {
  certificate_number: "AGNI-DEMO-2026-101",
  effective_status: "ACTIVE",
  premises_display_name: "Mehta Family Restaurant",
  locality: "Karol Bagh",
  issued_at: "2026-09-11T09:05:00Z",
  valid_until: "2027-09-11T09:05:00Z",
  issuer_label: "Agni Setu demonstration issuer (synthetic; not a government authority)",
  source: "REGISTRY",
  checked_at: "2026-09-11T10:00:00Z",
  is_demo: true,
  notice: "DEMONSTRATION - NOT AN OFFICIAL CERTIFICATE",
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders client={client}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
}

function stubFetch(handler: (url: string) => Response | null) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      const url = String(input);
      if (url === "/api/v1/me") return Promise.resolve(json(401, { code: "AUTHENTICATION_REQUIRED" }));
      const response = handler(url);
      return Promise.resolve(response ?? json(404, { code: "RESOURCE_NOT_FOUND" }));
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("VerifyPage (UI-18, public)", () => {
  it("shows an active demo record with the approved fields and the not-official marker", async () => {
    stubFetch((url) => (url === "/api/v1/public/certificates/tok-active" ? json(200, { data: ACTIVE }) : null));
    renderAt("/verify/tok-active");
    expect(await screen.findByRole("heading", { level: 2, name: "Verification result: Active" })).toBeInTheDocument();
    expect(screen.getByText("Not an official certificate - demonstration record")).toBeInTheDocument();
    expect(screen.getByText("AGNI-DEMO-2026-101")).toBeInTheDocument();
    expect(screen.getByText(/Mehta Family Restaurant/)).toBeInTheDocument();
    expect(screen.getByText(/Checked at/)).toBeInTheDocument();
  });

  it("distinguishes an unknown record from an outage and never shows ACTIVE on failure", async () => {
    stubFetch((url) => (url === "/api/v1/public/certificates/down" ? json(503, { code: "VERIFICATION_UNAVAILABLE", detail: "registry unreachable" }) : null));
    renderAt("/verify/unknown-token");
    expect(await screen.findByRole("heading", { level: 2, name: "Record not found" })).toBeInTheDocument();
    expect(screen.getByText(/not the same as a revoked certificate/)).toBeInTheDocument();
    vi.unstubAllGlobals();
    stubFetch((url) => (url === "/api/v1/public/certificates/down" ? json(503, { code: "VERIFICATION_UNAVAILABLE", detail: "registry unreachable" }) : null));
    renderAt("/verify/down");
    expect(await screen.findByRole("heading", { level: 2, name: "Unable to verify now" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByText("Verification result: Active")).not.toBeInTheDocument();
  });
});
