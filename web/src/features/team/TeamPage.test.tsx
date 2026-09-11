import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Grant, StaffList } from "../../api/staff";
import { AppProviders } from "../../app/providers";
import { routes } from "../../app/router";

const ADMIN = {
  id: "arjun",
  display_name: "Arjun Rao",
  kind: "STAFF",
  workspaces: ["admin", "policy"],
  active_workspace: "admin",
  scopes: [],
  capabilities: [],
  authz_epoch: 1,
  session_expires_at: "2026-09-10T10:00:00Z",
  feature_gates: { service_mode: "DEMO", demo_controls: true, staff_oidc: true },
};

const PROPOSED_BY_ME: Grant = {
  grant_id: "g1",
  subject_id: "anita",
  subject_display_name: "Anita Kapoor",
  capability: "certificate.status",
  scope_kind: "JURISDICTION",
  jurisdiction_id: "j1",
  service_id: null,
  state: "PROPOSED",
  effective_from: "2026-09-12T09:00:00Z",
  effective_until: null,
  preparer_id: "arjun",
  approver_id: null,
  approved_at: null,
  revoked_at: null,
  version: 1,
  etag: '"authority_grant:g1:v1"',
};

const PROPOSED_BY_OTHER: Grant = { ...PROPOSED_BY_ME, grant_id: "g2", capability: "case.decide", preparer_id: "second", etag: '"authority_grant:g2:v1"' };

const STAFF: StaffList = {
  scope: "GLOBAL",
  as_of: "2026-09-12T10:00:00Z",
  can_manage: true,
  items: [
    {
      principal_id: "anita",
      display_name: "Anita Kapoor",
      active: true,
      disabled_at: null,
      identity_bound: true,
      roles: [{ binding_id: "b1", role_key: "SUPERVISOR", jurisdiction_id: "j1", jurisdiction_code: "DEMO-CIRCLE-1", service_id: null, effective_from: "2026-01-01T00:00:00Z", effective_until: null, revoked_at: null, in_force: true }],
      grants: [],
      workload: { active_assignments: 0 },
      version: 3,
      etag: '"principal:anita:v3"',
    },
  ],
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

describe("TeamPage (UI-21)", () => {
  it("never offers approval of the administrator's own proposal and approves another's with the grant ETag", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, init });
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: ADMIN }));
        if (url === "/api/v1/auth/csrf") return Promise.resolve(json(200, { data: { csrf_token: "tok" } }));
        if (url === "/api/v1/staff") return Promise.resolve(json(200, { data: STAFF }));
        if (url === "/api/v1/authority-grants" && (!init?.method || init.method === "GET")) {
          return Promise.resolve(json(200, { data: { items: [PROPOSED_BY_ME, PROPOSED_BY_OTHER], as_of: STAFF.as_of } }));
        }
        if (url === "/api/v1/authority-grants/g2/approve" && init?.method === "POST") {
          return Promise.resolve(json(200, { data: { grant_id: "g2", state: "APPROVED" } }));
        }
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    renderAt("/team");
    expect(await screen.findByRole("heading", { level: 1, name: "Team and authority" })).toBeInTheDocument();
    expect(await screen.findByText("Prepared by you - another approver is required")).toBeInTheDocument();
    const approveButtons = screen.getAllByRole("button", { name: "Approve" });
    expect(approveButtons).toHaveLength(1);
    const user = userEvent.setup();
    await user.click(approveButtons[0]);
    await user.type(screen.getByLabelText("Approval basis"), "Approved at the circle governance meeting.");
    await user.click(screen.getByRole("button", { name: "Confirm approval" }));
    const post = requests.find((r) => r.url === "/api/v1/authority-grants/g2/approve" && r.init?.method === "POST");
    if (!post?.init) throw new Error("approval was not sent");
    const headers = post.init.headers as Record<string, string>;
    expect(headers["If-Match"]).toBe('"authority_grant:g2:v1"');
    expect(JSON.parse(post.init.body as string)).toEqual({ reason: "Approved at the circle governance meeting." });
    expect(screen.getByText("Roster")).toBeInTheDocument();
    expect(screen.getByText(/SUPERVISOR @ DEMO-CIRCLE-1/)).toBeInTheDocument();
  });
});
