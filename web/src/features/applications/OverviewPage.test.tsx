import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers";
import { routes } from "../../app/router";

const SUPERVISOR = {
  id: "s1",
  display_name: "Anita Kapoor",
  kind: "STAFF",
  workspaces: ["supervisor"],
  active_workspace: "supervisor",
  scopes: ["jurisdiction:CENTRAL-PILOT"],
  capabilities: [],
  authz_epoch: 1,
  session_expires_at: "2026-09-10T10:00:00Z",
  feature_gates: { service_mode: "DEMO", demo_controls: true, staff_oidc: true },
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

describe("OverviewPage (UI-09)", () => {
  it("shows supervisor KPIs from one cutoff with links to the filtered list", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        const url = String(input);
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: SUPERVISOR }));
        if (url === "/api/v1/overview") {
          return Promise.resolve(
            json(200, {
              data: {
                as_of: "2026-09-10T09:00:00Z",
                role: "staff",
                counts: { drafts: 0, open: 3, action_required: 0, review_waiting: 1, received: 3, by_status: { SUBMITTED: 2, REVIEW_PENDING: 1 }, due_soon: 2, overdue: 1, routing_exceptions: 1 },
                priority: [{ application_id: "a1", public_reference: "AS-2026-1001", kind: "SCRUTINY_TASK", due_at: "2026-09-11T09:00:00Z", owner_queue: "central-scrutiny" }],
                latest_events: [{ event_id: "e1", event_type: "application.submitted.v1", aggregate_version: 3, event_ordinal: 0, occurred_at: "2026-09-10T08:59:00Z", actor_kind: "APPLICANT", audience: "PUBLIC_CASE", payload: {}, application_id: "a1", public_reference: "AS-2026-1001" }],
              },
            }),
          );
        }
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    renderAt("/overview");
    expect(await screen.findByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    expect(await screen.findByText("Routing exceptions")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Review waiting/ })).toHaveAttribute("href", "/applications?status=REVIEW_PENDING");
    expect(screen.getByRole("link", { name: /Overdue/ })).toHaveTextContent("1");
    expect(screen.getByText(/SCRUTINY_TASK/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "AS-2026-1001" })).toHaveLength(2);
    // The workspace nav now links the supervisor to the overview.
    expect(screen.getByRole("navigation", { name: "Workspaces" })).toHaveTextContent("Supervisor");
  });
});
