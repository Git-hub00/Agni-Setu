import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers";
import { routes } from "../../app/router";

const OFFICER = {
  id: "o1",
  display_name: "Suresh Yadav",
  kind: "STAFF",
  workspaces: ["officer"],
  active_workspace: "officer",
  scopes: ["jurisdiction:CENTRAL-PILOT"],
  capabilities: [],
  authz_epoch: 1,
  session_expires_at: "2026-09-10T10:00:00Z",
  feature_gates: { service_mode: "DEMO", demo_controls: true, staff_oidc: true },
};

const INSPECTION = {
  inspection_id: "66666666-6666-4666-8666-666666666666",
  application_id: "a1",
  public_reference: "AS-2026-1001",
  application_status: "INSPECTION_PENDING",
  application_version: 5,
  attempt_number: 1,
  purpose: "INITIAL",
  parent_inspection_id: null,
  status: "SCHEDULED",
  checklist_ref: "demo-checklist-v1#1",
  premises: { display_name: "Mehta Family Restaurant", locality: "Karol Bagh", category_key: "Restaurant", ward_key: "W-01" },
  owner_queue: "central-scrutiny",
  scheduled_start: "2026-09-14T04:30:00+00:00",
  scheduled_end: "2026-09-14T06:30:00+00:00",
  appointment_timezone: "Asia/Kolkata",
  started_at: null,
  finished_at: null,
  check_in: null,
  failed_reason_code: null,
  failed_notes: null,
  cancel_reason: null,
  current_assignment: { assignment_id: "as1", number: 1, state: "ACTIVE", officer_id: "o1", officer_name: "Suresh Yadav", reason: "x", booking_start: "2026-09-14T04:30:00+00:00", booking_end: "2026-09-14T06:30:00+00:00", version: 1 },
  version: 2,
  updated_at: "2026-09-10T09:00:00Z",
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

describe("InspectionsQueuePage (UI-10)", () => {
  it("shows the officer's assigned attempts as cards with appointment and assignment version", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        const url = String(input);
        calls.push(url);
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: OFFICER }));
        if (url.startsWith("/api/v1/inspections")) return Promise.resolve(json(200, { data: { items: [INSPECTION], as_of: "2026-09-10T09:00:00Z" } }));
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    renderAt("/inspections?filter=upcoming");
    expect(await screen.findByRole("heading", { level: 1, name: "Inspections" })).toBeInTheDocument();
    expect(await screen.findByText("Mehta Family Restaurant")).toBeInTheDocument();
    expect(screen.getByText(/Suresh Yadav · v1/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upcoming" })).toHaveAttribute("aria-pressed", "true");
    expect(calls.some((u) => u === "/api/v1/inspections?state=SCHEDULED")).toBe(true);
    expect(screen.getByRole("link", { name: /Mehta Family Restaurant/ })).toHaveAttribute("href", `/inspections/${INSPECTION.inspection_id}`);
    expect(screen.getByRole("navigation", { name: "Workspaces" })).toHaveTextContent("Field officer");
  });
});
