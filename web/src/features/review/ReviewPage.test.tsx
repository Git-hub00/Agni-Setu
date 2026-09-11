import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DecisionReadiness } from "../../api/decisions";
import { AppProviders } from "../../app/providers";
import { routes } from "../../app/router";

const SUPERVISOR = {
  id: "s1",
  display_name: "Anita Kapoor",
  kind: "STAFF",
  workspaces: ["supervisor"],
  active_workspace: "supervisor",
  scopes: ["jurisdiction:CENTRAL-PILOT"],
  capabilities: ["case.decide"],
  authz_epoch: 1,
  session_expires_at: "2026-09-10T10:00:00Z",
  feature_gates: { service_mode: "DEMO", demo_controls: true, staff_oidc: true },
};

const CASE = {
  application_id: "a1",
  draft_reference: "DR-1",
  public_reference: "AS-2026-1001",
  status: "REVIEW_PENDING",
  service_key: "demo-fire-noc",
  premises: { premises_id: "p1", display_name: "Mehta Family Restaurant", category_key: "Restaurant", locality: "Karol Bagh" },
  owner_queue: "Central scrutiny desk",
  owner_queue_key: "central-scrutiny",
  submitted_at: "2026-09-10T08:00:00Z",
  next_due_at: "2026-09-12T11:30:00Z",
  created_at: "2026-09-10T07:00:00Z",
  updated_at: "2026-09-11T09:00:00Z",
  version: 9,
  premises_detail: { premises_id: "p1", display_name: "Mehta Family Restaurant", category_key: "Restaurant", locality: "Karol Bagh" },
  policy: { applicable: true, policy_version_id: "pv1", policy_number: 1, explanation: "", inspection_required: true, pinned_policy_version_id: "pv1" },
  draft: null,
  submission: { number: 1, accepted_at: "2026-09-10T08:00:00Z", policy_version_id: "pv1", policy_number: 1, sha256: "abcdef0123456789abcdef", fields: { category_key: "Restaurant", floor_count: 1 }, documents: [{ requirement_code: "plan", document_version_id: "d1" }] },
  obligations: [],
  inspections: [
    { inspection_id: "i1", attempt_number: 1, purpose: "INITIAL", status: "COMPLETED", scheduled_start: null, scheduled_end: null, appointment_timezone: "Asia/Kolkata", officer_name: "Priya Nair", failed_reason_code: null, report: { report_id: "r1", revision_number: 1, accepted_at: "2026-09-11T06:15:00Z", eligible_for_review: true, blockers: [], na_requiring_review: [] } },
  ],
  routing_exception: null,
  notices: [],
  findings_summary: { open_mandatory: 0, open_advisory: 0, verified_closed: 0, reinspection_outstanding: [] },
  decision: null,
  issuance: null,
  certificate: null,
  decision_readiness: null,
  allowed_actions: [
    { key: "approve", enabled: true, reason_code: null },
    { key: "reject", enabled: true, reason_code: null },
  ],
};

const READINESS: DecisionReadiness = {
  application_id: "a1",
  public_reference: "AS-2026-1001",
  status: "REVIEW_PENDING",
  version: 9,
  evidence: { submission_revision_id: "sr1", submission_number: 1, submission_sha256: "abcdef0123456789abcdef", report_id: "r1", report_revision: 1, report_sha256: "0123456789abcdef0123", report_eligible: true, policy_version_id: "pv1", policy_number: 1, open_mandatory_findings: [], reinspection_outstanding: [], open_notices: [] },
  authority: { grant_id: "g1-grant-id", scope: "JURISDICTION", inspector_cannot_decide: true, inspected_this_case: false },
  approve: { eligible: true, blockers: [] },
  reject: { eligible: true, blockers: [] },
  evaluated_at: "2026-09-11T09:00:00Z",
  notice: "Readiness is advisory.",
};

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
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

function stubFetch(readiness: DecisionReadiness, requests: { url: string; init?: RequestInit }[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (url === "/api/v1/me") return Promise.resolve(json(200, { data: SUPERVISOR }));
      if (url === "/api/v1/auth/csrf") return Promise.resolve(json(200, { data: { csrf_token: "tok" } }));
      if (url === "/api/v1/applications/a1" && (!init?.method || init.method === "GET")) {
        return Promise.resolve(json(200, { data: CASE }, { ETag: '"application:a1:v9"' }));
      }
      if (url === "/api/v1/applications/a1/decision-readiness") {
        return Promise.resolve(json(200, { data: readiness }, { ETag: '"application:a1:v9"' }));
      }
      if (url === "/api/v1/applications/a1/decisions" && init?.method === "POST") {
        const body = JSON.parse(init.body as string) as Record<string, unknown>;
        return Promise.resolve(
          json(201, {
            data: {
              decision_id: "dec1",
              decision_number: 1,
              kind: body.kind,
              application_id: "a1",
              public_reference: "AS-2026-1001",
              status: "APPROVED_PENDING_ISSUE",
              accepted_at: "2026-09-11T09:05:00Z",
              public_reason: body.public_reason,
              authority_grant_id: "g1-grant-id",
              evidence_sha256: "feedfacefeedfacefeedface",
              issuance: { issuance_request_id: "ir1", certificate_number: "AGNI-DEMO-2026-101", state: "READY" },
              command_id: "c1",
              replayed: false,
            },
          }),
        );
      }
      return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
    }),
  );
}

describe("ReviewPage (UI-14)", () => {
  it("requires an explicit acknowledgment and confirmation, then shows certificate processing - never issued", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    stubFetch(READINESS, requests);
    renderAt("/applications/a1/review");
    expect(await screen.findByRole("heading", { level: 1, name: /Evidence review and decision/ })).toBeInTheDocument();
    expect(await screen.findByText("Approval is available.")).toBeInTheDocument();
    const record = screen.getByRole("button", { name: "Record decision" });
    expect(record).toBeDisabled(); // nothing is preselected
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: "Approve" }));
    await user.type(screen.getByLabelText(/Internal rationale/), "Reviewed the record and the accepted report; everything is in order.");
    await user.type(screen.getByLabelText(/Public reason/), "The demonstration review is complete. Sample certificate processing has started.");
    expect(record).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    expect(record).toBeEnabled();
    await user.click(record);
    expect(await screen.findByRole("heading", { level: 3, name: "Confirm the decision" })).toBeInTheDocument();
    expect(screen.getByText(/Submission revision/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirm and record" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Approved - certificate processing" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/not issued until it appears in the register/);
    expect(screen.getByText(/AGNI-DEMO-2026-101/)).toBeInTheDocument();
    const post = requests.find((r) => r.url === "/api/v1/applications/a1/decisions" && r.init?.method === "POST");
    if (!post?.init) throw new Error("decision was not sent");
    const headers = post.init.headers as Record<string, string>;
    expect(headers["If-Match"]).toBe('"application:a1:v9"');
    expect(headers["Idempotency-Key"]).toMatch(/[0-9a-f-]{36}/);
    const body = JSON.parse(post.init.body as string) as Record<string, unknown>;
    expect(body).toMatchObject({ kind: "APPROVE", submission_revision_id: "sr1", report_id: "r1", review_acknowledged: true });
    expect(body).not.toHaveProperty("actor_id");
    expect(body).not.toHaveProperty("certificate_number");
  });

  it("keeps approval disabled while the server lists blockers", async () => {
    const blocked: DecisionReadiness = {
      ...READINESS,
      approve: { eligible: false, blockers: [{ code: "REPORT_NOT_ELIGIBLE", message: "The accepted report carries mandatory blockers", refs: ["MANDATORY_FAIL:C01"] }] },
    };
    stubFetch(blocked, []);
    renderAt("/applications/a1/review");
    expect(await screen.findByText(/REPORT_NOT_ELIGIBLE/)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Reject" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Record decision" })).toBeDisabled();
  });
});
