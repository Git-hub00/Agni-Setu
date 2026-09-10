import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers";
import { routes } from "../../app/router";

const PRINCIPAL = {
  id: "p1",
  display_name: "Applicant",
  kind: "APPLICANT",
  workspaces: ["applicant"],
  active_workspace: "applicant",
  scopes: [],
  capabilities: [],
  authz_epoch: 1,
  session_expires_at: "2026-09-10T10:00:00Z",
  feature_gates: { service_mode: "DEMO", demo_controls: true, staff_oidc: true },
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
  return router;
}

/** Routes fetch by URL so the sequence of calls does not matter. */
function stubApi(handlers: Partial<Record<string, (init?: RequestInit) => Response>>) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string, init?: RequestInit) => {
      const url = String(input).split("?")[0];
      calls.push({ url, init });
      const handler = handlers[url];
      if (!handler) return Promise.resolve(json(404, { code: "RESOURCE_NOT_FOUND" }));
      return Promise.resolve(handler(init));
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

describe("SignInPage", () => {
  it("sends a code, verifies it with CSRF, and navigates to the safe return path", async () => {
    let signedIn = false;
    const calls = stubApi({
      "/api/v1/auth/csrf": () => {
        document.cookie = "csrftoken=tok123";
        return json(200, { data: { csrf_token: "tok123" } });
      },
      "/api/v1/me": () => (signedIn ? json(200, { data: PRINCIPAL }) : json(401, { code: "AUTHENTICATION_REQUIRED" })),
      "/api/v1/auth/otp/challenges": () =>
        json(202, {
          data: {
            challenge_id: "c1",
            masked_destination: "r***@example.test",
            expires_at: new Date(Date.now() + 300_000).toISOString(),
            resend_available_at: new Date(Date.now() + 60_000).toISOString(),
          },
        }),
      "/api/v1/auth/otp/verify": () => {
        signedIn = true;
        return json(200, { data: PRINCIPAL });
      },
      "/api/v1/health/ready": () => json(200, { status: "ready", checks: {}, service_mode: "DEMO" }),
    });
    const user = userEvent.setup();
    const router = renderAt("/sign-in?next=%2Faccount");

    await user.type(screen.getByLabelText("Email address"), "rakesh.mehta@example.test");
    await user.click(screen.getByRole("button", { name: "Send code" }));

    expect(await screen.findByText("r***@example.test")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Six-digit code"), "123456");
    await user.click(screen.getByRole("button", { name: "Verify and sign in" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/account"));
    const verifyCall = calls.find((c) => c.url === "/api/v1/auth/otp/verify");
    expect(verifyCall?.init?.method).toBe("POST");
    expect((verifyCall?.init?.headers as Record<string, string>)["X-CSRFToken"]).toBe("tok123");
    expect(JSON.parse(verifyCall?.init?.body as string)).toEqual({
      challenge_id: "c1",
      code: "123456",
      channel: "EMAIL",
      contact: "rakesh.mehta@example.test",
    });
    expect(await screen.findByRole("heading", { level: 1, name: "Account" })).toBeInTheDocument();
  });

  it("shows a generic error for an invalid code and never a fake success", async () => {
    stubApi({
      "/api/v1/auth/csrf": () => {
        document.cookie = "csrftoken=tok123";
        return json(200, { data: { csrf_token: "tok123" } });
      },
      "/api/v1/me": () => json(401, { code: "AUTHENTICATION_REQUIRED" }),
      "/api/v1/auth/otp/challenges": () =>
        json(202, {
          data: {
            challenge_id: "c1",
            masked_destination: "r***@example.test",
            expires_at: new Date(Date.now() + 300_000).toISOString(),
            resend_available_at: new Date(Date.now() + 60_000).toISOString(),
          },
        }),
      "/api/v1/auth/otp/verify": () =>
        json(422, { type: "urn:agni-setu:problem:otp-invalid", code: "OTP_INVALID", status: 422, request_id: "req-9" }),
      "/api/v1/health/ready": () => json(200, { status: "ready", checks: {}, service_mode: "DEMO" }),
    });
    const user = userEvent.setup();
    const router = renderAt("/sign-in");

    await user.type(screen.getByLabelText("Email address"), "rakesh.mehta@example.test");
    await user.click(screen.getByRole("button", { name: "Send code" }));
    await user.type(await screen.findByLabelText("Six-digit code"), "000000");
    await user.click(screen.getByRole("button", { name: "Verify and sign in" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("That code is not valid");
    expect(alert).toHaveTextContent("req-9");
    expect(router.state.location.pathname).toBe("/sign-in");
    expect(screen.getByRole("button", { name: /Resend available in/ })).toBeDisabled();
  });

  it("offers staff sign-in through the provider and surfaces redirect errors", () => {
    stubApi({
      "/api/v1/me": () => json(401, { code: "AUTHENTICATION_REQUIRED" }),
      "/api/v1/health/ready": () => json(200, { status: "ready", checks: {}, service_mode: "DEMO" }),
    });
    renderAt("/sign-in?error=forbidden&next=//evil.example");
    const staffLink = screen.getByRole("link", { name: "Continue with staff identity" });
    expect(staffLink).toHaveAttribute("href", "/api/v1/auth/oidc/start?next=%2F");
    expect(screen.getByRole("alert")).toHaveTextContent("has not been provisioned");
    expect(screen.queryByText(/role/i)).not.toBeInTheDocument();
  });

  it("redirects anonymous visitors from protected routes to sign-in with a return path", async () => {
    stubApi({
      "/api/v1/me": () => json(401, { code: "AUTHENTICATION_REQUIRED" }),
      "/api/v1/health/ready": () => json(200, { status: "ready", checks: {}, service_mode: "DEMO" }),
    });
    const router = renderAt("/account");
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
    expect(router.state.location.search).toBe("?next=%2Faccount");
  });

  it("signs out and clears the session", async () => {
    let signedIn = true;
    stubApi({
      "/api/v1/auth/csrf": () => {
        document.cookie = "csrftoken=tok123";
        return json(200, { data: { csrf_token: "tok123" } });
      },
      "/api/v1/me": () => (signedIn ? json(200, { data: PRINCIPAL }) : json(401, { code: "AUTHENTICATION_REQUIRED" })),
      "/api/v1/auth/logout": () => {
        signedIn = false;
        return new Response(null, { status: 204 });
      },
      "/api/v1/health/ready": () => json(200, { status: "ready", checks: {}, service_mode: "DEMO" }),
    });
    const user = userEvent.setup();
    const router = renderAt("/account");
    expect(await screen.findByRole("heading", { level: 1, name: "Account" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Workspaces" })).toHaveTextContent("Applicant");
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
    expect(await screen.findByRole("link", { name: "Sign in" })).toBeInTheDocument();
  });
});
