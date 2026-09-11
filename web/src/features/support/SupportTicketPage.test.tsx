import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TicketDetail } from "../../api/support";
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

const TICKET: TicketDetail = {
  ticket_id: "t1",
  category: "TECHNICAL",
  subject: "Cannot open my inspection appointment",
  description: "The appointment page shows an error.",
  state: "WAITING_FOR_REQUESTER",
  priority: "NORMAL",
  application_id: "a1",
  public_reference: "AS-2026-1001",
  owner_queue: "central-scrutiny",
  requester_id: "p1",
  resolved_at: null,
  closed_at: null,
  created_at: "2026-09-11T08:00:00Z",
  updated_at: "2026-09-11T09:00:00Z",
  version: 3,
  etag: '"ticket:t1:v3"',
  notice: "Support tickets are not an emergency channel.",
  messages: [
    { message_id: "m1", kind: "MESSAGE", audience: "REQUESTER", sender_id: "p1", body: "The appointment page shows an error.", document_version_ids: [], state_after: "OPEN", created_at: "2026-09-11T08:00:00Z" },
    { message_id: "m2", kind: "MESSAGE", audience: "REQUESTER", sender_id: "s1", body: "Please try again after clearing the app cache.", document_version_ids: [], state_after: "IN_PROGRESS", created_at: "2026-09-11T08:30:00Z" },
    { message_id: "m3", kind: "STATUS", audience: "REQUESTER", sender_id: "s1", body: "IN_PROGRESS -> WAITING_FOR_REQUESTER: waiting for confirmation", document_version_ids: [], state_after: "WAITING_FOR_REQUESTER", created_at: "2026-09-11T09:00:00Z" },
  ],
  is_requester: true,
  support_scope: false,
  allowed_actions: [
    { key: "reply", enabled: true, reason_code: null },
    { key: "internal-note", enabled: false, reason_code: "STAFF_ONLY" },
    { key: "status:IN_PROGRESS", enabled: false, reason_code: "NOT_PERMITTED" },
    { key: "status:RESOLVED", enabled: false, reason_code: "NOT_PERMITTED" },
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

describe("SupportTicketPage (UI-26)", () => {
  it("shows the requester conversation without internal controls and replies with the ticket ETag", async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, init });
        if (url === "/api/v1/me") return Promise.resolve(json(200, { data: APPLICANT }));
        if (url === "/api/v1/auth/csrf") return Promise.resolve(json(200, { data: { csrf_token: "tok" } }));
        if (url === "/api/v1/tickets/t1" && (!init?.method || init.method === "GET")) {
          return Promise.resolve(json(200, { data: TICKET }, { ETag: TICKET.etag }));
        }
        if (url === "/api/v1/tickets/t1/messages" && init?.method === "POST") {
          return Promise.resolve(json(201, { data: { message_id: "m4", kind: "MESSAGE", audience: "REQUESTER", sender_id: "p1", body: "Cleared the cache; it works now.", document_version_ids: [], state_after: "IN_PROGRESS", created_at: "2026-09-11T09:10:00Z", ticket_state: "IN_PROGRESS" } }));
        }
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    renderAt("/support/t1");
    expect(await screen.findByRole("heading", { level: 1, name: "Cannot open my inspection appointment" })).toBeInTheDocument();
    expect(screen.getByText("Please try again after clearing the app cache.")).toBeInTheDocument();
    expect(screen.getByText(/WAITING_FOR_REQUESTER: waiting for confirmation/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Internal note/)).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Support status" })).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Message"), "Cleared the cache; it works now.");
    await user.click(screen.getByRole("button", { name: "Send" }));
    const post = requests.find((r) => r.url === "/api/v1/tickets/t1/messages" && r.init?.method === "POST");
    if (!post?.init) throw new Error("reply was not sent");
    const headers = post.init.headers as Record<string, string>;
    expect(headers["If-Match"]).toBe('"ticket:t1:v3"');
    expect(JSON.parse(post.init.body as string)).toEqual({ body: "Cleared the cache; it works now.", audience: "REQUESTER" });
  });
});
