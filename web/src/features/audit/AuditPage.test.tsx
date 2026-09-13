import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers";
import { routes } from "../../app/router";

const PRINCIPAL = {
  id: "s1",
  display_name: "Arjun Rao",
  kind: "STAFF",
  workspaces: ["admin"],
  active_workspace: "admin",
  scopes: [],
  capabilities: [],
  authz_epoch: 1,
  session_expires_at: "2026-09-13T10:00:00Z",
  feature_gates: { service_mode: "DEMO", demo_controls: true, staff_oidc: true },
};

const EVENT = {
  audit_event_id: "a1",
  entity_type: "application",
  entity_id: "19906b76-bc5c-45e4-9061-c1d8b00cbda2",
  action: "application.draft_created",
  actor_id: "p1",
  authority_grant_id: null,
  request_id: "r1",
  timestamp: "2026-09-13T00:01:18Z",
  summary: {},
  redacted: false,
  hash: "h1",
  prior_hash: null,
  checkpoint_batch_id: null,
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

describe("AuditPage (UI-23)", () => {
  it("keeps the events table inside a positioned scroll card so a wide result set never widens the page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        const url = String(input);
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: PRINCIPAL }));
        if (url.startsWith("/api/v1/audit-events")) {
          return Promise.resolve(
            json(200, { data: { items: [EVENT], has_more: false, redacted: false, as_of: "2026-09-13T00:02:00Z", notice: "Every search is recorded." } }),
          );
        }
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    renderAt("/audit");
    expect(await screen.findByRole("heading", { level: 1, name: "Audit trail" })).toBeInTheDocument();
    expect(await screen.findByText("application.draft_created")).toBeInTheDocument();
    const table = screen.getByRole("table");
    // jsdom applies no stylesheet, so the contract is the card's utility classes: the scroll
    // container must also be positioned, otherwise the absolutely positioned sr-only "Open"
    // header escapes the clipped card and widens the page (regression #1: 179 px at 360 px).
    const card = table.closest("section");
    expect(card).toHaveClass("overflow-x-auto");
    expect(card).toHaveClass("relative");
    expect(card?.querySelector("th .sr-only")).not.toBeNull();
  });
});
