import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
const APP_ID = "44444444-4444-4444-8444-444444444444";

function detail(revision: number, locality: string) {
  return {
    application_id: APP_ID,
    draft_reference: "DR-2026-ABC123",
    public_reference: null,
    status: "DRAFT",
    service_key: "demo-fire-noc",
    premises: { premises_id: "pr1", display_name: "Mehta Family Restaurant", category_key: "Restaurant", locality },
    owner_queue: "Central scrutiny desk",
    submitted_at: null,
    created_at: "2026-09-10T08:00:00Z",
    updated_at: "2026-09-10T08:00:00Z",
    version: revision,
    premises_detail: {},
    policy: { applicable: true, policy_version_id: "pv1", policy_number: 1, explanation: "Policy version 1 applies", inspection_required: true },
    draft: {
      draft_revision: revision,
      form_schema_ref: "premises-v1#1",
      saved_at: "2026-09-10T08:00:00Z",
      fields: { display_name: "Mehta Family Restaurant", locality, category_key: "Restaurant", application_type: "NEW" },
      declaration_drafts: [],
      declarations: [{ code: "D01", version: "1", text: "I declare that the information provided is true." }],
      attachment_links: [],
      documents: [],
      requirements: [{ code: "ownership", label: "Premises authorization", required: true, status: "MISSING", document_version_id: null }],
      blockers: [{ code: "DECLARATION_MISSING", pointer: "/declaration_drafts/D01" }],
    },
    allowed_actions: [{ key: "edit-draft", enabled: true, reason_code: null }, { key: "submit", enabled: false, reason_code: "DRAFT_INCOMPLETE" }],
  };
}

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

describe("ApplicationWizardPage (UI-06)", () => {
  it("autosaves edits with the draft revision, If-Match and an idempotency key", async () => {
    document.cookie = "csrftoken=test-token";
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, init });
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: PRINCIPAL }));
        if (url === `/api/v1/applications/${APP_ID}` && (init?.method ?? "GET") === "GET") {
          return Promise.resolve(json(200, { data: detail(1, "Karol Bagh") }, { ETag: `"application:${APP_ID}:v1"` }));
        }
        if (url === `/api/v1/applications/${APP_ID}/draft`) {
          const saved = { ...detail(2, "Patel Nagar").draft, application_id: APP_ID, version: 2 };
          return Promise.resolve(json(200, { data: saved }, { ETag: `"application:${APP_ID}:v2"` }));
        }
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    renderAt(`/applications/${APP_ID}/edit`);
    const user = userEvent.setup();
    await screen.findByRole("heading", { level: 1, name: /DR-2026-ABC123/ });
    await user.click(screen.getByRole("button", { name: /2\. Details and declarations/ }));
    const locality = screen.getByLabelText("Locality");
    await user.clear(locality);
    await user.type(locality, "Patel Nagar");
    expect(screen.getByRole("status")).toHaveAttribute("data-save-state", "dirty");

    await waitFor(() => expect(screen.getByRole("status")).toHaveAttribute("data-save-state", "saved"), { timeout: 3000 });
    const patches = calls.filter((c) => c.url.endsWith("/draft"));
    expect(patches).toHaveLength(1); // debounced: one save for the whole typing burst
    const headers = new Headers(patches[0].init?.headers);
    expect(headers.get("If-Match")).toBe(`"application:${APP_ID}:v1"`);
    expect(headers.get("X-CSRFToken")).toBe("test-token");
    expect(headers.get("Idempotency-Key")).toMatch(/[0-9a-f-]{36}/);
    const body = JSON.parse(patches[0].init?.body as string) as { draft_revision: number; fields: Record<string, unknown> };
    expect(body.draft_revision).toBe(1);
    expect(body.fields).toEqual({ locality: "Patel Nagar" });
  });

  it("warns before the page unloads while edits are unsaved, and stays quiet once saved (UI-1139/UI-1141, G-08)", async () => {
    document.cookie = "csrftoken=test-token";
    const gate: { release: (() => void) | null } = { release: null };
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: PRINCIPAL }));
        if (url === `/api/v1/applications/${APP_ID}` && (init?.method ?? "GET") === "GET") {
          return Promise.resolve(json(200, { data: detail(1, "Karol Bagh") }, { ETag: `"application:${APP_ID}:v1"` }));
        }
        if (url === `/api/v1/applications/${APP_ID}/draft`) {
          // Hold the save until the test releases it, so the "saving" window is observable.
          return new Promise<Response>((resolve) => {
            gate.release = () => {
              const saved = { ...detail(2, "Patel Nagar").draft, application_id: APP_ID, version: 2 };
              resolve(json(200, { data: saved }, { ETag: `"application:${APP_ID}:v2"` }));
            };
          });
        }
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    const unload = () => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    };
    renderAt(`/applications/${APP_ID}/edit`);
    const user = userEvent.setup();
    await screen.findByRole("heading", { level: 1, name: /DR-2026-ABC123/ });
    expect(unload(), "nothing edited yet: no prompt").toBe(false);
    await user.click(screen.getByRole("button", { name: /2\. Details and declarations/ }));
    const locality = screen.getByLabelText("Locality");
    await user.clear(locality);
    await user.type(locality, "Patel Nagar");
    expect(screen.getByRole("status")).toHaveAttribute("data-save-state", "dirty");
    expect(unload(), "unsaved edits: the browser must ask before leaving").toBe(true);
    await waitFor(() => expect(screen.getByRole("status")).toHaveAttribute("data-save-state", "saving"), { timeout: 3000 });
    expect(unload(), "save in flight: still guarded").toBe(true);
    gate.release?.();
    await waitFor(() => expect(screen.getByRole("status")).toHaveAttribute("data-save-state", "saved"), { timeout: 3000 });
    expect(unload(), "everything saved: no prompt").toBe(false);
  });

  it("shows a conflict with field differences on 412 instead of overwriting", async () => {
    document.cookie = "csrftoken=test-token";
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: PRINCIPAL }));
        if (url === `/api/v1/applications/${APP_ID}` && (init?.method ?? "GET") === "GET") {
          return Promise.resolve(json(200, { data: detail(1, "Karol Bagh") }, { ETag: `"application:${APP_ID}:v1"` }));
        }
        if (url === `/api/v1/applications/${APP_ID}/draft`) {
          return Promise.resolve(
            json(412, {
              code: "VERSION_CONFLICT",
              detail: "The draft was saved elsewhere since you loaded it",
              current_version: 2,
              current_draft_revision: 2,
              current_fields: { locality: "Rajendra Nagar" },
            }),
          );
        }
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    renderAt(`/applications/${APP_ID}/edit`);
    const user = userEvent.setup();
    await screen.findByRole("heading", { level: 1, name: /DR-2026-ABC123/ });
    await user.click(screen.getByRole("button", { name: /2\. Details and declarations/ }));
    const locality = screen.getByLabelText("Locality");
    await user.clear(locality);
    await user.type(locality, "Patel Nagar");

    const alert = await screen.findByRole("alert", {}, { timeout: 3000 });
    expect(alert).toHaveTextContent("This draft was changed elsewhere");
    expect(alert).toHaveTextContent("Rajendra Nagar");
    expect(alert).toHaveTextContent("Patel Nagar");
    expect(screen.getByRole("status")).toHaveAttribute("data-save-state", "conflict");
    expect(screen.getByRole("button", { name: "Use saved version" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Reapply my edits" })).toBeEnabled();
  });
});
