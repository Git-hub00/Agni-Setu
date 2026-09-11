import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CaseDetail } from "../../api/applications";
import { AppProviders } from "../../app/providers";
import { routes } from "../../app/router";

const APPLICANT = {
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

const CASE: CaseDetail = {
  application_id: "a1",
  draft_reference: "DR-1",
  public_reference: "AS-2026-1001",
  status: "INSPECTION_PENDING",
  service_key: "demo-fire-noc",
  premises: { premises_id: "p1", display_name: "Mehta Family Restaurant", category_key: "Restaurant", locality: "Karol Bagh" },
  owner_queue: "Central scrutiny desk",
  owner_queue_key: "central-scrutiny",
  submitted_at: "2026-09-10T08:00:00Z",
  next_due_at: null,
  created_at: "2026-09-10T07:00:00Z",
  updated_at: "2026-09-11T09:00:00Z",
  version: 5,
  premises_detail: { premises_id: "p1", display_name: "Mehta Family Restaurant", category_key: "Restaurant", locality: "Karol Bagh" } as CaseDetail["premises_detail"],
  policy: { applicable: true, policy_version_id: "pv1", policy_number: 1, explanation: "", inspection_required: true, pinned_policy_version_id: "pv1" },
  draft: null,
  submission: { number: 1, accepted_at: "2026-09-10T08:00:00Z", policy_version_id: "pv1", policy_number: 1, sha256: "abc", fields: {}, documents: [] },
  obligations: [],
  inspections: [],
  routing_exception: null,
  notices: [],
  findings_summary: null,
  decision: null,
  issuance: null,
  certificate: null,
  decision_readiness: null,
  on_hold: false,
  holds: null,
  prior_certificate_id: null,
  closed_at: null,
  allowed_actions: [
    { key: "edit-draft", enabled: false, reason_code: "NOT_EDITABLE" },
    { key: "withdraw", enabled: true, reason_code: null },
  ],
};

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CaseLifecycleActions - withdrawal (UI-07, TR-13)", () => {
  it("requires a reason and a confirmation, then sends the reasoned command with If-Match", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, init });
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: APPLICANT }));
        if (url === "/api/v1/auth/csrf") return Promise.resolve(json(200, { data: { csrf_token: "tok" } }));
        if (url === "/api/v1/applications/a1" && (!init?.method || init.method === "GET")) {
          return Promise.resolve(json(200, { data: CASE }, { ETag: '"application:a1:v5"' }));
        }
        if (url === "/api/v1/applications/a1/timeline") return Promise.resolve(json(200, { data: { items: [], as_of: "2026-09-11T09:00:00Z" } }));
        if (url === "/api/v1/applications/a1/withdraw" && init?.method === "POST") {
          return Promise.resolve(json(200, { data: { status: "WITHDRAWN", from_status: "INSPECTION_PENDING", disposition: {} } }));
        }
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const router = createMemoryRouter(routes, { initialEntries: ["/applications/a1"] });
    render(
      <AppProviders client={client}>
        <RouterProvider router={router} />
      </AppProviders>,
    );
    expect(await screen.findByRole("heading", { level: 2, name: "Case lifecycle" })).toBeInTheDocument();
    const user = userEvent.setup();
    const withdraw = screen.getByRole("button", { name: "Withdraw application" });
    expect(withdraw).toBeDisabled();
    await user.type(screen.getByLabelText("Reason (recorded)"), "We sold the premises before the visit could take place.");
    expect(withdraw).toBeEnabled();
    await user.click(withdraw);
    expect(screen.getByText("Confirm the withdrawal")).toBeInTheDocument();
    expect(requests.some((r) => r.url.endsWith("/withdraw"))).toBe(false);
    await user.click(screen.getByRole("button", { name: "Yes, withdraw" }));
    const post = requests.find((r) => r.url === "/api/v1/applications/a1/withdraw" && r.init?.method === "POST");
    if (!post?.init) throw new Error("withdrawal was not sent");
    const headers = post.init.headers as Record<string, string>;
    expect(headers["If-Match"]).toBe('"application:a1:v5"');
    expect(JSON.parse(post.init.body as string)).toEqual({ reason: "We sold the premises before the visit could take place." });
  });
});
