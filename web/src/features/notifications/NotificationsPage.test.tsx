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

const PAGE = {
  items: [
    {
      notification_id: "n1",
      category: "NOTICE",
      mandatory: true,
      title: "Information required for AS-2026-1001",
      body: "A notice with 2 item(s) asks for information. Respond by 2026-09-17.",
      target_path: "/applications/a1/notices/x1",
      application_id: "a1",
      created_at: "2026-09-10T08:00:00Z",
      read_at: null,
      deliveries: [{ channel: "EMAIL", state: "FAILED", destination_masked: "a***@example.test", sent_at: null, failure_code: "PROVIDER_UNAVAILABLE", attempts: 1 }],
    },
  ],
  next_cursor: null,
  has_more: false,
  unread_count: 1,
  as_of: "2026-09-10T09:00:00Z",
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

describe("NotificationsPage (UI-19)", () => {
  it("keeps the in-app notice visible when e-mail failed and marks read through the seen boundary", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, init });
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: APPLICANT }));
        if (url === "/api/v1/auth/csrf") return Promise.resolve(json(200, { data: { csrf_token: "tok" } }));
        if (url === "/api/v1/notifications") return Promise.resolve(json(200, { data: PAGE }));
        if (url === "/api/v1/me/preferences" && (!init?.method || init.method === "GET")) {
          return Promise.resolve(json(200, { data: { locale: "en", optional_channels: [], reduced_motion: false, mandatory_note: "Mandatory service messages cannot be disabled." } }));
        }
        if (url === "/api/v1/notifications/read-through" && init?.method === "POST") {
          return Promise.resolve(json(200, { data: { through: PAGE.as_of, marked_read: 1, unread_count: 0 } }));
        }
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    renderAt("/notifications");
    expect(await screen.findByRole("heading", { level: 1, name: /Notifications/ })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 2, name: "Information required for AS-2026-1001" })).toBeInTheDocument();
    expect(screen.getByText(/e-mail failed - this in-app notice stands/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open" })).toHaveAttribute("href", "/applications/a1/notices/x1");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Mark all read (up to now)" }));
    const post = requests.find((r) => r.url === "/api/v1/notifications/read-through" && r.init?.method === "POST");
    if (!post?.init) throw new Error("read-through was not sent");
    expect(JSON.parse(post.init.body as string)).toEqual({ through: PAGE.as_of });
    expect(screen.getByRole("link", { name: "Notifications" })).toHaveAttribute("href", "/notifications");
  });
});
