import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

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

const NOTICE = {
  notice_id: "77777777-7777-4777-8777-777777777777",
  application_id: "a1",
  round_number: 1,
  type: "INFORMATION",
  state: "PUBLISHED",
  public_reason: "The submitted ownership proof cannot be read; one clarification.",
  published_at: "2026-09-10T09:00:00Z",
  response_budget_minutes: 10080,
  due_at: "2026-09-17T09:00:00Z",
  obligation_state: "ACTIVE",
  supersedes_id: null,
  superseded_by_id: null,
  closed_at: null,
  version: 1,
  items: [
    {
      notice_item_id: "i1",
      notice_id: "77777777-7777-4777-8777-777777777777",
      code: "INFO-01",
      title: "Ownership proof is illegible",
      description: "Upload a legible copy of the ownership document (all pages).",
      required: true,
      acceptable_evidence_types: ["DOCUMENT"],
      public_guidance: null,
      state: "RETURNED",
      finding_id: null,
      finding_state: null,
      finding_severity: null,
      reviewer_feedback: "Page 2 is missing from the scan.",
      current_response_id: "r1",
      verified_at: null,
      version: 3,
      responses: [{ response_revision_id: "r1", number: 1, explanation: "First scan attached.", document_version_ids: [], accepted_at: "2026-09-10T10:00:00Z", sha256: "abc" }],
      reviews: [],
    },
    {
      notice_item_id: "i2",
      notice_id: "77777777-7777-4777-8777-777777777777",
      code: "INFO-02",
      title: "Optional floor plan clarification",
      description: "If available, mark the assembly points on the floor plan.",
      required: false,
      acceptable_evidence_types: ["DOCUMENT", "WRITTEN_EXPLANATION"],
      public_guidance: "A hand-drawn sketch is acceptable for the demonstration.",
      state: "OPEN",
      finding_id: null,
      finding_state: null,
      finding_severity: null,
      reviewer_feedback: null,
      current_response_id: null,
      verified_at: null,
      version: 1,
      responses: [],
      reviews: [],
    },
  ],
  open_items: 2,
  items_total: 2,
  application_status: "INFO_REQUIRED",
  application_version: 7,
  public_reference: "AS-2026-1001",
  evidence_types: ["DOCUMENT", "PHOTOGRAPH"],
  allowed_actions: [
    { key: "respond", enabled: true, reason_code: null },
    { key: "review-item", enabled: false, reason_code: "NOTHING_TO_REVIEW" },
    { key: "verify-finding", enabled: false, reason_code: "NOT_AUTHORIZED" },
    { key: "accept-information", enabled: false, reason_code: "NOT_AVAILABLE" },
  ],
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

describe("NoticePage (UI-08, applicant)", () => {
  it("shows the returned item with feedback, never styles received as verified, and submits replies with the notice ETag", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, init });
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: APPLICANT }));
        if (url === "/api/v1/auth/csrf") return Promise.resolve(json(200, { data: { csrf_token: "tok" } }));
        if (url === `/api/v1/notices/${NOTICE.notice_id}` && (!init?.method || init.method === "GET")) {
          return Promise.resolve(json(200, { data: NOTICE }, { ETag: `"notice:${NOTICE.notice_id}:v1"` }));
        }
        if (url.endsWith("/responses") && init?.method === "POST") {
          return Promise.resolve(json(201, { data: { ...NOTICE, responses: [{ code: "INFO-01", number: 2, item_state: "RESPONSE_RECEIVED" }] } }, { ETag: `"notice:${NOTICE.notice_id}:v2"` }));
        }
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    renderAt(`/applications/a1/notices/${NOTICE.notice_id}`);
    expect(await screen.findByRole("heading", { level: 1, name: /Information required · round 1/ })).toBeInTheDocument();
    expect(screen.getByText(/Reviewer feedback:/)).toHaveTextContent("Page 2 is missing from the scan.");
    expect(screen.getByText("Returned: action needed")).toBeInTheDocument();
    expect(screen.getByText("Awaiting your response")).toBeInTheDocument();
    expect(screen.queryByText(/Verified/)).not.toBeInTheDocument();
    expect(screen.getByText(/Reply 1/).closest("li")).toHaveTextContent("First scan attached.");

    const user = userEvent.setup();
    const submit = screen.getByRole("button", { name: /Submit replies/ });
    expect(submit).toBeDisabled();
    const explanations = screen.getAllByLabelText("Explanation");
    await user.type(explanations[0], "Attached a scanned, legible copy of all three pages.");
    await user.click(screen.getByRole("checkbox", { name: /I confirm the information/ }));
    expect(submit).toBeEnabled();
    await user.click(submit);
    expect(await screen.findByText(/Replies received/)).toBeInTheDocument();
    const post = requests.find((r) => r.url.endsWith("/responses") && r.init?.method === "POST");
    if (!post?.init) throw new Error("no response submission sent");
    const headers = post.init.headers as Record<string, string>;
    expect(headers["If-Match"]).toBe(`"notice:${NOTICE.notice_id}:v1"`);
    const body = JSON.parse(post.init.body as string) as { application_version: number; declaration_accepted: boolean; responses: { notice_item_id: string; explanation: string; document_version_ids: string[] }[] };
    expect(body.application_version).toBe(7);
    expect(body.declaration_accepted).toBe(true);
    expect(body.responses).toEqual([{ notice_item_id: "i1", explanation: "Attached a scanned, legible copy of all three pages.", document_version_ids: [] }]);
  });
});
