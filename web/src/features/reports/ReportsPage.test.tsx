import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ExportJob, Metrics } from "../../api/reporting";
import { AppProviders } from "../../app/providers";
import { routes } from "../../app/router";

const SUPERVISOR = {
  id: "s1",
  display_name: "Anita Kapoor",
  kind: "STAFF",
  workspaces: ["supervisor"],
  active_workspace: "supervisor",
  scopes: [],
  capabilities: [],
  authz_epoch: 1,
  session_expires_at: "2026-09-10T10:00:00Z",
  feature_gates: { service_mode: "DEMO", demo_controls: true, staff_oidc: true },
};

const METRICS: Metrics = {
  as_of: "2026-09-12T10:00:00Z",
  definition_version: "metrics-v1",
  scope: { kind: "JURISDICTIONS", jurisdiction_ids: ["j1"] },
  filters: {},
  population: 7,
  metrics: {
    received: 7,
    open: 4,
    completed: 2,
    rejected: 1,
    withdrawn: 0,
    published_certificates: 2,
    overdue_obligations: 1,
    resolution_hours: { sample_size: 3, median: 40.5, p90: 52, insufficient_sample: true },
  },
  by_status: { SCRUTINY: 2, INSPECTION_PENDING: 2, COMPLETED: 2, REJECTED: 1 },
  reconciled: true,
  exclusions: { drafts: 3 },
  definitions: { received: "Applications with a receipt at or before the cutoff.", open: "Not terminal." },
};

const EXPORT: ExportJob = {
  export_id: "e1",
  kind: "CASES",
  field_set_key: "case-summary",
  fields: ["public_reference"],
  purpose: "Monthly review pack for the circle",
  filters: {},
  scope: { kind: "JURISDICTIONS" },
  population: 7,
  as_of: "2026-09-12T10:00:00Z",
  definition_version: "metrics-v1",
  state: "COMPLETE",
  row_count: 7,
  expires_at: "2099-01-01T00:00:00Z",
  last_error_code: null,
  requester_id: "s1",
  created_at: "2026-09-12T10:00:00Z",
  updated_at: "2026-09-12T10:01:00Z",
  version: 2,
  etag: '"export:e1:v2"',
  scope_valid: true,
  allowed_actions: [{ key: "access", enabled: true, reason_code: null }],
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

describe("ReportsPage (UI-22)", () => {
  it("shows reconciled metrics with definitions and requests an export with a purpose", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, init });
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: SUPERVISOR }));
        if (url === "/api/v1/auth/csrf") return Promise.resolve(json(200, { data: { csrf_token: "tok" } }));
        if (url.startsWith("/api/v1/reports/summary")) return Promise.resolve(json(200, { data: METRICS }));
        if (url === "/api/v1/exports" && (!init?.method || init.method === "GET")) return Promise.resolve(json(200, { data: { items: [EXPORT], as_of: METRICS.as_of } }));
        if (url === "/api/v1/exports" && init?.method === "POST") return Promise.resolve(json(202, { data: { ...EXPORT, export_id: "e2", state: "READY", row_count: null } }));
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    renderAt("/reports");
    expect(await screen.findByRole("heading", { level: 1, name: "Reports and exports" })).toBeInTheDocument();
    expect(await screen.findByText("Totals reconcile")).toBeInTheDocument();
    expect(screen.getByText("Applications with a receipt at or before the cutoff.")).toBeInTheDocument();
    expect(screen.getByText(/Insufficient sample/)).toBeInTheDocument();
    expect(screen.getByText("SCRUTINY: 2")).toBeInTheDocument();
    expect(await screen.findByText(/Monthly review pack for the circle/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download" })).toBeEnabled();
    const user = userEvent.setup();
    const button = screen.getByRole("button", { name: "Request export" });
    expect(button).toBeDisabled();
    await user.type(screen.getByLabelText(/Purpose/), "Monthly review pack for the circle");
    expect(button).toBeEnabled();
    await user.click(button);
    const post = requests.find((r) => r.url === "/api/v1/exports" && r.init?.method === "POST");
    if (!post?.init) throw new Error("export was not requested");
    const headers = post.init.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toBeTruthy();
    expect(JSON.parse(post.init.body as string)).toEqual({
      kind: "CASES",
      field_set_key: "case-summary",
      purpose: "Monthly review pack for the circle",
      filters: {},
      format: "CSV",
    });
  });
});
