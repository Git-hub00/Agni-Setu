import { createBrowserRouter, type RouteObject } from "react-router";

import { NotFoundPage } from "./NotFoundPage";
import { RouteErrorBoundary } from "./RouteErrorBoundary";
import { AppShell } from "./layouts/AppShell";
import { PremisesPage } from "../features/applicant/PremisesPage";
import { ApplicationDetailPage } from "../features/applications/ApplicationDetailPage";
import { ApplicationsListPage } from "../features/applications/ApplicationsListPage";
import { ApplicationWizardPage } from "../features/applications/ApplicationWizardPage";
import { NewApplicationPage } from "../features/applications/NewApplicationPage";
import { HomePage } from "../features/home/HomePage";
import { AccountPage } from "../features/identity/AccountPage";
import { RequireSession } from "../features/identity/RequireSession";
import { SignInPage } from "../features/identity/SignInPage";
import { PolicyDetailPage } from "../features/policy/PolicyDetailPage";
import { PolicyListPage } from "../features/policy/PolicyListPage";

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
      { path: "sign-in", element: <SignInPage /> },
      {
        element: <RequireSession />,
        children: [
          { path: "account", element: <AccountPage /> },
          { path: "applicant/premises", element: <PremisesPage /> },
          { path: "applications", element: <ApplicationsListPage /> },
          { path: "applications/new", element: <NewApplicationPage /> },
          { path: "applications/:applicationId", element: <ApplicationDetailPage /> },
          { path: "applications/:applicationId/edit", element: <ApplicationWizardPage /> },
          { path: "policy", element: <PolicyListPage /> },
          { path: "policy/:policyId", element: <PolicyDetailPage /> },
        ],
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export function createAppRouter() {
  return createBrowserRouter(routes);
}
