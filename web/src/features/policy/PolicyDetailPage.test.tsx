import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers";
import { routes } from "../../app/router";

const APPROVER = {
  id: "meera",
  display_name: "Meera Shah",
  kind: "STAFF",
  workspaces: ["policy"],
  active_workspace: "policy",
  scopes: [],
  capabilities: ["POLICY_APPROVE"],
  authz_epoch: 1,
  session_expires_at: "2026-09-10T10:00:00Z",
  feature_gates: { service_mode: "DEMO", demo_controls: true, staff_oidc: true },
};

const POLICY_ID = "33333333-3333-4333-8333-333333333333";
const DETAIL = {
  policy_version_id: POLICY_ID,
  service_key: "demo-fire-noc",
  jurisdiction_code: "CENTRAL-PILOT",
  number: 2,
  state: "IN_REVIEW",
  payload_sha256: "a".repeat(64),
  review_candidate_sha256: "a".repeat(64),
  effective_from: null,
  effective_until: null,
  prepared_by: "arjun",
  approved_by: null,
  version: 3,
  updated_at: "2026-09-10T09:00:00Z",
  payload: { key: "DEMO-DEPARTMENT-REVIEW" },
  schema_version: "1.0",
  approval_basis: "",
  returned_reason: "",
  source_references: [],
  contributors: [{ principal_id: "arjun-0000", action: "CREATE", at: "2026-09-10T08:00:00Z" }],
  simulations: [{ simulation_id: "s1", candidate_sha256: "a".repeat(64), suite: "demo-baseline-v1", passed: true, completed_at: "2026-09-10T08:30:00Z" }],
  allowed_actions: [
    { key: "edit", enabled: false, reason_code: "NOT_EDITABLE" },
    { key: "submit-review", enabled: false, reason_code: "NOT_EDITABLE" },
    { key: "simulate", enabled: true, reason_code: null },
    { key: "approve", enabled: true, reason_code: null },
    { key: "return", enabled: true, reason_code: null },
    { key: "activate", enabled: false, reason_code: "NOT_APPROVED" },
  ],
};

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
}

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders client={client}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

describe("PolicyDetailPage (UI-24)", () => {
  it("shows the governance record, enables only server-allowed actions and posts approve with If-Match", async () => {
    document.cookie = "csrftoken=test-token";
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, init });
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: APPROVER }));
        if (url === `/api/v1/policies/${POLICY_ID}` && (init?.method ?? "GET") === "GET") {
          return Promise.resolve(json(200, { data: DETAIL }, { ETag: `"policy_version:${POLICY_ID}:v3"` }));
        }
        if (url === `/api/v1/policies/${POLICY_ID}/approve`) {
          return Promise.resolve(json(200, { data: { ...DETAIL, state: "APPROVED" } }));
        }
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    renderAt(`/policy/${POLICY_ID}`);

    expect(await screen.findByRole("heading", { level: 1, name: /demo-fire-noc v2/ })).toBeInTheDocument();
    expect(screen.getByText("Passed", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Activate" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Submit for review" })).toBeDisabled();
    const approve = screen.getByRole("button", { name: "Approve" });
    expect(approve).toBeDisabled(); // no reason yet

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Reason (recorded in the audit trail)"), "Independent approval of v2");
    await user.type(screen.getByLabelText("Effective from"), "2026-10-01T00:00");
    expect(approve).toBeEnabled();
    await user.click(approve);

    expect(await screen.findByRole("status")).toHaveTextContent("Done: Approve");
    const post = calls.find((c) => c.url.endsWith("/approve"));
    const headers = new Headers(post?.init?.headers);
    expect(headers.get("If-Match")).toBe(`"policy_version:${POLICY_ID}:v3"`);
    expect(headers.get("X-CSRFToken")).toBe("test-token");
    expect(headers.get("Idempotency-Key")).toMatch(/[0-9a-f-]{36}/);
    const body = JSON.parse(post?.init?.body as string) as Record<string, unknown>;
    expect(body.candidate_sha256).toBe("a".repeat(64));
    expect(body.reason).toBe("Independent approval of v2");
    expect(typeof body.effective_from).toBe("string");
  });

  it("exposes the scrollable payload as a keyboard-reachable named region (WCAG 2.1.1, UI-1178)", async () => {
    document.cookie = "csrftoken=test-token";
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: APPROVER }));
        if (url === `/api/v1/policies/${POLICY_ID}` && (init?.method ?? "GET") === "GET") {
          return Promise.resolve(json(200, { data: DETAIL }, { ETag: `"policy_version:${POLICY_ID}:v3"` }));
        }
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    renderAt(`/policy/${POLICY_ID}`);
    await screen.findByRole("heading", { level: 1, name: /demo-fire-noc v2/ });
    // The payload block scrolls (max-h + overflow); a scrollable region must be focusable so that
    // keyboard users can scroll it (axe `scrollable-region-focusable`, serious).
    const payload = screen.getByRole("region", { name: "Payload JSON (scrollable)" });
    expect(payload.tagName).toBe("PRE");
    expect(payload).toHaveAttribute("tabindex", "0");
    expect(payload).toHaveTextContent("DEMO-DEPARTMENT-REVIEW");
  });
});
