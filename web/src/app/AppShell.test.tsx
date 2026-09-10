import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "./providers";
import { routes } from "./router";
import { WORKSPACE_KEYS } from "./layouts/AppShell";

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(
    <AppProviders client={client}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
}

function stubFetch(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AppShell", () => {
  it("renders the accessible shell landmarks and seven disabled workspace placeholders", () => {
    stubFetch(200, { status: "ready", checks: {}, service_mode: "DEMO" });
    renderAt("/");

    const skip = screen.getByRole("link", { name: "Skip to main content" });
    expect(skip).toHaveAttribute("href", "#main-content");
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAttribute("id", "main-content");
    expect(screen.getByRole("contentinfo")).toHaveTextContent(
      "Demonstration build - not an official government service",
    );

    const nav = screen.getByRole("navigation", { name: "Workspaces" });
    const placeholders = within(nav).getAllByText("coming in a later phase");
    expect(placeholders).toHaveLength(7);
    expect(WORKSPACE_KEYS).toHaveLength(7);
    expect(within(nav).queryAllByRole("link")).toHaveLength(0);
  });

  it("renders the not-found page for unknown routes with a home link", () => {
    stubFetch(200, { status: "ready", checks: {}, service_mode: "DEMO" });
    renderAt("/nothing/here");

    expect(screen.getByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
  });
});
