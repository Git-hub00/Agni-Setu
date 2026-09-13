import { QueryClient } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
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
  session_expires_at: "2026-09-13T10:00:00Z",
  feature_gates: { service_mode: "DEMO", demo_controls: true, staff_oidc: true },
};

const UNAVAILABLE = {
  type: "about:blank",
  title: "Service Unavailable",
  status: 503,
  code: "DEPENDENCY_UNAVAILABLE",
  detail: "The service is temporarily unavailable; nothing was recorded. Retry the same command shortly.",
  retry_after_seconds: 30,
  request_id: "req-503-1",
};

function json(status: number, body: unknown, contentType = "application/json"): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": contentType } });
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

describe("RequireSession (security s.4, DEF-013)", () => {
  it("shows a transient 503 as the problem it is and retries the session bootstrap in place", async () => {
    let attempts = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        const url = String(input);
        if (url === "/api/v1/me") {
          attempts += 1;
          if (attempts === 1) return Promise.resolve(json(503, UNAVAILABLE, "application/problem+json"));
          return Promise.resolve(json(200, { data: PRINCIPAL }));
        }
        if (url.startsWith("/api/v1/applications")) {
          return Promise.resolve(json(200, { data: { items: [], next_cursor: null, has_more: false } }));
        }
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    renderAt("/applications");
    const alert = await screen.findByRole("alert");
    // The problem itself, its retry-after guidance and its reference are shown, not a bare message.
    expect(alert).toHaveTextContent("DEPENDENCY_UNAVAILABLE");
    expect(alert).toHaveTextContent("30");
    expect(alert).toHaveTextContent("req-503-1");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Applications" })).toBeInTheDocument();
    expect(attempts).toBe(2);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("still sends anonymous visitors to sign-in with the return path", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        const url = String(input);
        if (url === "/api/v1/me") return Promise.resolve(json(401, { code: "UNAUTHENTICATED" }, "application/problem+json"));
        return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      }),
    );
    renderAt("/applications?status=DRAFT");
    expect(await screen.findByRole("heading", { level: 1, name: "Applicant sign-in" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });
});
