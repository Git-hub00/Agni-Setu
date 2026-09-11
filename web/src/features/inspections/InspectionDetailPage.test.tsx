import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers";
import { routes } from "../../app/router";

const OFFICER = {
  id: "o1",
  display_name: "Priya Nair",
  kind: "STAFF",
  workspaces: ["officer"],
  active_workspace: "officer",
  scopes: ["jurisdiction:CENTRAL-PILOT"],
  capabilities: [],
  authz_epoch: 1,
  session_expires_at: "2026-09-10T10:00:00Z",
  feature_gates: { service_mode: "DEMO", demo_controls: true, staff_oidc: true },
};

const ITEMS = [
  { code: "C01", title: "Means of escape", mandatory: true, evidence_required: true, na_permitted: false },
  { code: "C04", title: "Fire-water and suppression provision", mandatory: true, evidence_required: true, na_permitted: true },
  { code: "C07", title: "Emergency access observations", mandatory: false, evidence_required: false, na_permitted: true },
];

const INSPECTION = {
  inspection_id: "66666666-6666-4666-8666-666666666666",
  application_id: "a1",
  public_reference: "AS-2026-1001",
  application_status: "INSPECTION_PENDING",
  application_version: 5,
  attempt_number: 1,
  purpose: "INITIAL",
  parent_inspection_id: null,
  status: "IN_PROGRESS",
  checklist_ref: "demo-checklist-v1#2",
  premises: { display_name: "Mehta Family Restaurant", locality: "Karol Bagh", category_key: "Restaurant", ward_key: "W-01" },
  owner_queue: "central-scrutiny",
  scheduled_start: "2026-09-14T04:30:00+00:00",
  scheduled_end: "2026-09-14T06:30:00+00:00",
  appointment_timezone: "Asia/Kolkata",
  started_at: "2026-09-14T04:32:00+00:00",
  finished_at: null,
  check_in: { location: null },
  failed_reason_code: null,
  failed_notes: null,
  cancel_reason: null,
  current_assignment: { assignment_id: "as1", number: 1, state: "ACTIVE", officer_id: "o1", officer_name: "Priya Nair", reason: "x", booking_start: "2026-09-14T04:30:00+00:00", booking_end: "2026-09-14T06:30:00+00:00", version: 1 },
  version: 3,
  updated_at: "2026-09-14T04:32:00Z",
  checklist_items: ITEMS,
  assignments: [],
  allowed_actions: [
    { key: "schedule", enabled: false, reason_code: "NOT_AUTHORIZED" },
    { key: "check-in", enabled: false, reason_code: null },
    { key: "fail-visit", enabled: true, reason_code: null },
    { key: "save-draft", enabled: true, reason_code: null },
    { key: "submit-report", enabled: true, reason_code: null },
  ],
  draft: {
    draft_id: "d1",
    inspection_id: "66666666-6666-4666-8666-666666666666",
    base_inspection_version: 3,
    assignment_version: 1,
    observations: [{ item_code: "C07", result: "NOT_APPLICABLE", note: "Single frontage; no separate access question", document_version_ids: [] }],
    summary: "",
    captured_at: null,
    local_revision: 2,
    saved_at: "2026-09-14T05:00:00Z",
    version: 2,
  },
  report: null,
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

describe("InspectionDetailPage report workspace (UI-12)", () => {
  // Many typed interactions: allow more than the 5 s default on slow or busy hosts.
  it("restores the server draft, enforces notes for non-pass results and submits with the inspection ETag", { timeout: 20000 }, async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, init });
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: OFFICER }));
        if (url === "/api/v1/auth/csrf") return Promise.resolve(json(200, { data: { csrf_token: "tok" } }));
        if (url === `/api/v1/inspections/${INSPECTION.inspection_id}` && (!init?.method || init.method === "GET")) {
          return Promise.resolve(json(200, { data: INSPECTION }, { ETag: `"inspection:${INSPECTION.inspection_id}:v3"` }));
        }
        if (url.endsWith("/reports") && init?.method === "POST") {
          const body = JSON.parse(init.body as string) as Record<string, unknown>;
          return Promise.resolve(
            json(201, {
              data: {
                ...INSPECTION,
                status: "COMPLETED",
                report: {
                  report_id: "r1",
                  inspection_id: INSPECTION.inspection_id,
                  revision_number: 1,
                  checklist_ref: "demo-checklist-v1#2",
                  submitted_by: "o1",
                  captured_at: body.captured_at,
                  capture_unavailable_reason: null,
                  accepted_at: "2026-09-14T06:15:00Z",
                  observations: body.observations,
                  summary: body.summary,
                  evaluation: {
                    eligible_for_review: false,
                    blockers: [{ code: "MANDATORY_FAIL", item_code: "C01", message: "Means of escape: mandatory item failed" }],
                    findings: [],
                    na_requiring_review: ["C07"],
                    counts: { PASS: 1, FAIL: 1, NOT_VERIFIED: 0, NOT_APPLICABLE: 1 },
                    scoring: "none",
                  },
                  sha256: "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
                  evidence: [],
                },
                receipt: { report_id: "r1", revision_number: 1, sha256: "abc", accepted_at: "2026-09-14T06:15:00Z", inspection_version: 4, application_version: 6, application_status: "REVIEW_PENDING" },
              },
            }),
          );
        }
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    renderAt(`/inspections/${INSPECTION.inspection_id}`);
    expect(await screen.findByRole("heading", { name: "Observations and report" })).toBeInTheDocument();
    // Draft restored: C07 already NOT_APPLICABLE with its rationale.
    const list = screen.getAllByRole("listitem");
    const row = (title: string): HTMLElement => {
      const found = list.find((li) => li.textContent.includes(title));
      if (!found) throw new Error(`no row for ${title}`);
      return found;
    };
    const c07 = row("Emergency access observations");
    expect(within(c07).getByRole("combobox")).toHaveValue("NOT_APPLICABLE");
    // C01 does not offer NOT_APPLICABLE (policy forbids it).
    const c01 = row("Means of escape");
    expect(within(c01).queryByRole("option", { name: "Not applicable" })).not.toBeInTheDocument();

    const user = userEvent.setup();
    const submit = screen.getByRole("button", { name: "Submit report" });
    expect(submit).toBeDisabled();
    await user.selectOptions(within(c01).getByRole("combobox"), "FAIL");
    expect(within(c01).getByRole("textbox")).toHaveAccessibleName("Explanation (required for this result)");
    await user.type(within(c01).getByRole("textbox"), "Rear escape route padlocked and stacked with cartons");
    const c04 = row("Fire-water");
    await user.selectOptions(within(c04).getByRole("combobox"), "PASS");
    await user.type(screen.getByLabelText("Visit summary"), "Escape route blocked; everything else in order.");
    expect(submit).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    expect(submit).toBeEnabled();
    await user.click(submit);

    expect(await screen.findByRole("heading", { name: "Accepted report" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Mandatory blockers recorded");
    expect(screen.getByRole("status")).toHaveTextContent("C01 · Means of escape: mandatory item failed");
    expect(screen.getByText(/Case status now:/)).toHaveTextContent("REVIEW_PENDING");
    const post = requests.find((r) => r.url.endsWith("/reports") && r.init?.method === "POST");
    if (!post?.init) throw new Error("report submission was not sent");
    const headers = post.init.headers as Record<string, string>;
    expect(headers["If-Match"]).toBe(`"inspection:${INSPECTION.inspection_id}:v3"`);
    expect(headers["Idempotency-Key"]).toMatch(/[0-9a-f-]{36}/);
    const body = JSON.parse(post.init.body as string) as { observations: { item_code: string; result: string }[]; declaration_accepted: boolean; assignment_version: number; checklist_version: string };
    expect(body.declaration_accepted).toBe(true);
    expect(body.assignment_version).toBe(1);
    expect(body.checklist_version).toBe("demo-checklist-v1#2");
    expect(body.observations.map((o) => `${o.item_code}:${o.result}`)).toEqual(["C01:FAIL", "C04:PASS", "C07:NOT_APPLICABLE"]);
  });
});
