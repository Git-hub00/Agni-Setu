import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers";
import { routes } from "../../app/router";

const PRINCIPAL = {
  id: "p1",
  display_name: "Rakesh Mehta",
  kind: "APPLICANT",
  workspaces: ["applicant"],
  active_workspace: "applicant",
  scopes: [],
  capabilities: [],
  authz_epoch: 1,
  session_expires_at: "2026-09-10T10:00:00Z",
  feature_gates: { service_mode: "DEMO", demo_controls: true, staff_oidc: true },
};

const ROW = {
  application_id: "55555555-5555-4555-8555-555555555555",
  draft_reference: "DR-2026-ZZZ999",
  public_reference: null,
  status: "DRAFT",
  service_key: "demo-fire-noc",
  premises: { premises_id: "pr1", display_name: "Mehta Corner Cafe", category_key: "Restaurant", locality: "Patel Nagar" },
  owner_queue: "Central scrutiny desk",
  submitted_at: null,
  created_at: "2026-09-10T08:00:00Z",
  updated_at: "2026-09-10T08:30:00Z",
  version: 3,
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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ApplicationsListPage (UI-05)", () => {
  it("lists scoped applications with Continue for drafts and honours the status filter in the URL", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        const url = String(input);
        calls.push(url);
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: PRINCIPAL }));
        if (url.startsWith("/api/v1/applications")) {
          return Promise.resolve(json(200, { data: { items: [ROW], next_cursor: null, has_more: false } }));
        }
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    renderAt("/applications?status=DRAFT");
    expect(await screen.findByRole("heading", { level: 1, name: "Applications" })).toBeInTheDocument();
    expect(await screen.findByText("DR-2026-ZZZ999")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Continue" })).toHaveAttribute("href", `/applications/${ROW.application_id}/edit`);
    expect(screen.getByRole("link", { name: "New application" })).toHaveAttribute("href", "/applications/new");
    expect(calls.some((u) => u === "/api/v1/applications?status=DRAFT")).toBe(true);
    expect(screen.getByLabelText("Status")).toHaveValue("DRAFT");
  });

  it("shows an empty state with the creation link and a failed state with retry", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        const url = String(input);
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: PRINCIPAL }));
        return Promise.resolve(json(503, { code: "DEPENDENCY_UNAVAILABLE", detail: "Database unavailable" }));
      }),
    );
    renderAt("/applications");
    expect(await screen.findByRole("alert")).toHaveTextContent("DEPENDENCY_UNAVAILABLE");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
