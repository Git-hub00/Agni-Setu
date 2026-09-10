import { createBrowserRouter, type RouteObject } from "react-router";

import { NotFoundPage } from "./NotFoundPage";
import { RouteErrorBoundary } from "./RouteErrorBoundary";
import { AppShell } from "./layouts/AppShell";
import { HomePage } from "../features/home/HomePage";

/**
 * SPA browser router (ADR-03, architecture s.2). Every deep route is also checked server-side;
 * routes for the seven workspaces are mounted here as their phases land, behind feature gates.
 */
export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    errorElement: <RouteErrorBoundary />,
    children: [
      { index: true, element: <HomePage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export function createAppRouter() {
  return createBrowserRouter(routes);
}
