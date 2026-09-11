import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers";
import { routes } from "../../app/router";

const PRINCIPAL = {
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

const PREMISES = {
  premises_id: "11111111-1111-4111-8111-111111111111",
  owner_id: "p1",
  display_name: "Mehta Family Restaurant",
  address_line1: "1 Demo Road",
  address_line2: "",
  locality: "Karol Bagh",
  ward_key: "W-01",
  postal_code: "110005",
  category_key: "Restaurant",
  area_sqm: "320.00",
  height_m: "7.50",
  floor_count: 2,
  occupancy_count: 120,
  version: 1,
  updated_at: "2026-09-10T09:00:00Z",
};

const SERVICE = {
  service_id: "22222222-2222-4222-8222-222222222222",
  key: "demo-fire-noc",
  title: "Demonstration fire safety certificate",
  mode: "DEMO",
  available: true,
  explanation: "Synthetic demonstration service.",
  allowed_categories: ["Restaurant", "Hospital"],
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
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

function stubApi(handlers: Partial<Record<string, (init?: RequestInit) => Response>>) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string, init?: RequestInit) => {
      const url = String(input).split("?")[0];
      calls.push({ url, init });
      const handler = handlers[url];
      return Promise.resolve(handler ? handler(init) : json(404, { code: "RESOURCE_NOT_FOUND" }));
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

describe("PremisesPage (UI-04)", () => {
  it("lists owned premises and shows the nonbinding applicability preview", async () => {
    document.cookie = "csrftoken=test-token";
    const calls = stubApi({
      "/api/v1/me": () => json(200, { data: PRINCIPAL }),
      "/api/v1/premises": () => json(200, { data: { items: [PREMISES], next_cursor: null, has_more: false } }),
      "/api/v1/services": () => json(200, { data: { items: [SERVICE], service_mode: "DEMO" } }),
      [`/api/v1/services/${SERVICE.service_id}/applicability`]: () =>
        json(200, {
          data: {
            applicable: true,
            explanation: "Demo policy v1 applies to Hospital premises.",
            policy_version_id: "pv1",
            policy_number: 1,
            payload_sha256: "abc",
            form_schema_ref: "premises-v1#1",
            checklist_ref: "demo-checklist-v1#1",
            required_documents: ["ownership", "plan", "electrical", "evacuation"],
            inspection_required: true,
            allowed_categories: ["Restaurant", "Hospital"],
            binding: false,
          },
        }),
    });
    renderAt("/applicant/premises");

    expect(await screen.findByRole("heading", { level: 1, name: "My premises" })).toBeInTheDocument();
    expect(await screen.findByText("Mehta Family Restaurant")).toBeInTheDocument();
    // The workspace entry became a real link once the session granted it.
    const nav = screen.getByRole("navigation", { name: "Workspaces" });
    expect(within(nav).getByRole("link", { name: "Applicant" })).toHaveAttribute("href", "/applications");

    const user = userEvent.setup();
    await screen.findByRole("option", { name: /Demonstration fire safety certificate/ });
    await user.selectOptions(screen.getByLabelText("Service"), SERVICE.service_id);
    await user.selectOptions(screen.getByLabelText("Premises category"), "Hospital");
    await user.click(screen.getByRole("button", { name: "Preview requirements" }));

    const result = await screen.findByTestId("applicability-result");
    expect(within(result).getByText("evacuation")).toBeInTheDocument();
    expect(within(result).getByText("Preview only - not a decision")).toBeInTheDocument();

    const post = calls.find((c) => c.url.endsWith("/applicability"));
    expect(post?.init?.method).toBe("POST");
    expect(new Headers(post?.init?.headers).get("X-CSRFToken")).toBe("test-token");
    expect(JSON.parse(post?.init?.body as string)).toEqual({ declared_category: "Hospital" });
  });

  it("registers premises with an idempotency key and surfaces field violations", async () => {
    document.cookie = "csrftoken=test-token";
    let attempts = 0;
    const calls = stubApi({
      "/api/v1/me": () => json(200, { data: PRINCIPAL }),
      "/api/v1/services": () => json(200, { data: { items: [], service_mode: "DEMO" } }),
      "/api/v1/premises": (init) => {
        if (init?.method === "POST") {
          attempts += 1;
          return json(422, {
            code: "VALIDATION_FAILED",
            detail: "Validation failed",
            violations: [{ pointer: "/postal_code", code: "format", message: "must be a 6-digit postal code" }],
          });
        }
        return json(200, { data: { items: [], next_cursor: null, has_more: false } });
      },
    });
    renderAt("/applicant/premises");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Premises name"), "Mehta Corner Cafe");
    await user.type(screen.getByLabelText("Address"), "12 Market Street");
    await user.type(screen.getByLabelText("Locality"), "Patel Nagar");
    await user.type(screen.getByLabelText("Ward key"), "W-06");
    await user.type(screen.getByLabelText("Postal code"), "12");
    await user.type(screen.getByLabelText("Category"), "Restaurant");
    await user.type(screen.getByLabelText("Built-up area (sq m)"), "95");
    await user.type(screen.getByLabelText("Height (m)"), "4.2");
    await user.click(screen.getByRole("button", { name: "Register" }));

    expect(await screen.findByText("must be a 6-digit postal code")).toBeInTheDocument();
    expect(attempts).toBe(1);
    const post = calls.find((c) => c.url === "/api/v1/premises" && c.init?.method === "POST");
    expect(new Headers(post?.init?.headers).get("Idempotency-Key")).toMatch(/[0-9a-f-]{36}/);
  });
});
