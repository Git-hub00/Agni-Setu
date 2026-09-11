import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Integration, IntegrationConflict } from "../../api/integrations";
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

const PARTNER: Integration = {
  integration_id: "i1",
  key: "demo-partner-case-source",
  display_name: "Demo partner case source (simulated)",
  mode: "SIMULATED",
  provider_kind: "partner_case_source",
  state: "ENABLED",
  capabilities: ["receive_event", "lookup_case"],
  system_of_record_fields: ["source_status"],
  endpoint_allowlist: ["simulated://partner-case-source"],
  credential_secret_ref: "DEMO_PARTNER_SHARED_SECRET",
  credential_configured: true,
  owner_queue: "central-review",
  freshness: "FRESH",
  freshness_budget_seconds: 86400,
  last_event_at: "2026-09-12T09:00:00Z",
  last_health_status: "OK",
  last_health_at: "2026-09-12T09:05:00Z",
  last_health_detail: "simulated connectivity probe answered (no partner workflow proven)",
  allowed_tests: ["connectivity", "auth", "schema"],
  open_conflicts: 1,
  inbox_counts: { RECEIVED: 0, PROCESSED: 3, QUARANTINED: 0, CONFLICT: 1 },
  notice: "A Connected or OK badge is not evidence of an end-to-end regulatory integration; SIMULATED and SANDBOX modes never carry live legal effect.",
  version: 4,
  etag: '"integration:i1:v4"',
};

const CONFLICT: IntegrationConflict = {
  conflict_id: "c1",
  integration_id: "i1",
  integration_key: "demo-partner-case-source",
  source_entity_id: "UPG-DEMO-2026-0001",
  reason_code: "SEQUENCE_GAP",
  detail: { expected_sequence: 2, received_sequence: 4, applied_sequence: 1 },
  owner_queue: "central-review",
  state: "OPEN",
  outcome: null,
  resolution_basis: null,
  resolved_by_id: null,
  resolved_at: null,
  inbox: null,
  created_at: "2026-09-12T09:10:00Z",
  updated_at: "2026-09-12T09:10:00Z",
  version: 1,
  etag: '"integration_conflict:c1:v1"',
  allowed_outcomes: ["APPLY_VERIFIED_SOURCE", "IGNORE_DUPLICATE", "REQUEST_RESEND", "KEEP_QUARANTINED"],
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

describe("IntegrationsPage (UI-25)", () => {
  it("shows the mode badge without secret values and resolves a conflict with evidence and the conflict ETag", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, init });
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: ADMIN }));
        if (url === "/api/v1/auth/csrf") return Promise.resolve(json(200, { data: { csrf_token: "tok" } }));
        if (url === "/api/v1/integrations") return Promise.resolve(json(200, { data: { items: [PARTNER], as_of: "2026-09-12T09:20:00Z" } }));
        if (url === "/api/v1/integration-conflicts?state=OPEN") return Promise.resolve(json(200, { data: { items: [CONFLICT], as_of: "2026-09-12T09:20:00Z", scope: "GLOBAL" } }));
        if (url === "/api/v1/integration-conflicts/c1/resolve" && init?.method === "POST") {
          return Promise.resolve(json(200, { data: { ...CONFLICT, state: "RESOLVED", outcome: "APPLY_VERIFIED_SOURCE", applied_sequence: 4 } }));
        }
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    renderAt("/integrations");
    expect(await screen.findByRole("heading", { level: 1, name: "Integrations" })).toBeInTheDocument();
    expect(screen.getByText("SIMULATED")).toBeInTheDocument();
    expect(screen.getByText(/Secret reference DEMO_PARTNER_SHARED_SECRET/)).toBeInTheDocument();
    expect(screen.queryByText(/demo-partner-shared-secret-not-for-live/)).not.toBeInTheDocument();
    expect(await screen.findByText(/SEQUENCE_GAP · UPG-DEMO-2026-0001/)).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Resolve" }));
    const confirm = screen.getByRole("button", { name: "Confirm resolution" });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText("Authoritative source version"), "v4");
    await user.type(screen.getByLabelText(/Verification evidence/), "lookup:sim-1, partner-email:2026-09-12");
    await user.type(screen.getByLabelText("Reason"), "Verified against the partner lookup during the drill.");
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    const post = requests.find((r) => r.url === "/api/v1/integration-conflicts/c1/resolve" && r.init?.method === "POST");
    if (!post?.init) throw new Error("resolution was not sent");
    const headers = post.init.headers as Record<string, string>;
    expect(headers["If-Match"]).toBe('"integration_conflict:c1:v1"');
    expect(JSON.parse(post.init.body as string)).toEqual({
      outcome: "APPLY_VERIFIED_SOURCE",
      reason: "Verified against the partner lookup during the drill.",
      authoritative_source_version: "v4",
      verification_evidence_refs: ["lookup:sim-1", "partner-email:2026-09-12"],
    });
  });
});
