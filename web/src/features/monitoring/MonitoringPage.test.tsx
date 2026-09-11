import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

const ROW = {
  obligation_id: "88888888-8888-4888-8888-888888888888",
  application_id: "a1",
  public_reference: "AS-2026-1001",
  application_status: "SCRUTINY",
  kind: "SCRUTINY_TASK",
  state: "ACTIVE",
  urgency: "OVERDUE",
  time_basis: "WORKING",
  budget_minutes: 480,
  started_at: "2026-09-08T03:30:00+00:00",
  due_at: "2026-09-09T11:30:00+00:00",
  owner_queue: "central-scrutiny",
  responsible_principal: null,
  generation: 1,
  open_escalations: [
    {
      escalation_id: "e1",
      obligation_id: "88888888-8888-4888-8888-888888888888",
      threshold_action_id: "t1",
      manual: false,
      level: 1,
      owner_queue: "central-scrutiny",
      state: "OPEN",
      reason: "Threshold ESCALATION_60 reached",
      requested_by: null,
      acknowledged_by: null,
      acknowledged_at: null,
      next_action: null,
      created_at: "2026-09-09T12:30:00+00:00",
      version: 1,
    },
  ],
  etag: '"obligation:88888888-8888-4888-8888-888888888888:v3"',
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

describe("MonitoringPage (UI-15)", () => {
  it("shows counts and overdue rows from one cutoff and acknowledges an escalation with its ETag", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, init });
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: SUPERVISOR }));
        if (url === "/api/v1/auth/csrf") return Promise.resolve(json(200, { data: { csrf_token: "tok" } }));
        if (url.startsWith("/api/v1/obligations?") || url === "/api/v1/obligations") {
          return Promise.resolve(json(200, { data: { as_of: "2026-09-10T09:00:00Z", counts: { overdue: 1, due_soon: 0, paused: 0, open_escalations: 1 }, items: [ROW] } }));
        }
        if (url.endsWith("/acknowledge") && init?.method === "POST") {
          return Promise.resolve(json(200, { data: { ...ROW.open_escalations[0], state: "ACKNOWLEDGED", obligation_state: "ACTIVE", version: 2 } }));
        }
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    renderAt("/monitoring?tab=overdue");
    expect(await screen.findByRole("heading", { level: 1, name: "Obligations and escalations" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Overdue" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByText("AS-2026-1001")).toBeInTheDocument();
    expect(screen.getByText(/Escalation level 1 · OPEN/)).toBeInTheDocument();
    expect(requests.some((r) => r.url === "/api/v1/obligations?urgency=OVERDUE")).toBe(true);
    // Acknowledging needs a reason; the escalation ETag travels in If-Match.
    const user = userEvent.setup();
    const ack = screen.getByRole("button", { name: "Acknowledge" });
    expect(ack).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Show clock" }));
    await user.type(screen.getByLabelText(/Reason/), "Taking ownership of the overdue scrutiny");
    expect(ack).toBeEnabled();
    await user.click(ack);
    const post = requests.find((r) => r.url.endsWith("/acknowledge") && r.init?.method === "POST");
    if (!post?.init) throw new Error("acknowledge was not sent");
    expect((post.init.headers as Record<string, string>)["If-Match"]).toBe('"escalation:e1:v1"');
    expect(JSON.parse(post.init.body as string)).toEqual({ reason: "Taking ownership of the overdue scrutiny" });
    expect(screen.getByRole("navigation", { name: "Workspaces" })).toHaveTextContent("Monitoring");
  });
});
