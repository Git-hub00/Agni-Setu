import { createBrowserRouter, type RouteObject } from "react-router";

import { NotFoundPage } from "./NotFoundPage";
import { RouteErrorBoundary } from "./RouteErrorBoundary";
import { AppShell } from "./layouts/AppShell";
import { PremisesPage } from "../features/applicant/PremisesPage";
import { ApplicationDetailPage } from "../features/applications/ApplicationDetailPage";
import { ApplicationsListPage } from "../features/applications/ApplicationsListPage";
import { ApplicationWizardPage } from "../features/applications/ApplicationWizardPage";
import { NewApplicationPage } from "../features/applications/NewApplicationPage";
import { OverviewPage } from "../features/applications/OverviewPage";
import { AuditPage } from "../features/audit/AuditPage";
import { CertificateDetailPage } from "../features/certificates/CertificateDetailPage";
import { CertificatesPage } from "../features/certificates/CertificatesPage";
import { IntegrationsPage } from "../features/integrations/IntegrationsPage";
import { ReportsPage } from "../features/reports/ReportsPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { TeamPage } from "../features/team/TeamPage";
import { ReviewPage } from "../features/review/ReviewPage";
import { ReviewQueuePage } from "../features/review/ReviewQueuePage";
import { SupportPage } from "../features/support/SupportPage";
import { SupportTicketPage } from "../features/support/SupportTicketPage";
import { VerifyPage } from "../features/verify/VerifyPage";
import { InspectionDetailPage } from "../features/inspections/InspectionDetailPage";
import { InspectionsQueuePage } from "../features/inspections/InspectionsQueuePage";
import { SchedulePage } from "../features/inspections/SchedulePage";
import { MonitoringPage } from "../features/monitoring/MonitoringPage";
import { NoticePage } from "../features/notices/NoticePage";
import { NotificationsPage } from "../features/notifications/NotificationsPage";
import { OperationsPage } from "../features/operations/OperationsPage";
import { SyncPage } from "../features/sync/SyncPage";
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
      { path: "verify", element: <VerifyPage /> },
      { path: "verify/:token", element: <VerifyPage /> },
      {
        element: <RequireSession />,
        children: [
          { path: "account", element: <AccountPage /> },
          { path: "applicant/premises", element: <PremisesPage /> },
          { path: "overview", element: <OverviewPage /> },
          { path: "inspections", element: <InspectionsQueuePage /> },
          { path: "inspections/:inspectionId", element: <InspectionDetailPage /> },
          { path: "schedule", element: <SchedulePage /> },
          { path: "applications", element: <ApplicationsListPage /> },
          { path: "applications/new", element: <NewApplicationPage /> },
          { path: "applications/:applicationId", element: <ApplicationDetailPage /> },
          { path: "applications/:applicationId/edit", element: <ApplicationWizardPage /> },
          { path: "applications/:applicationId/notices/:noticeId", element: <NoticePage /> },
          { path: "applications/:applicationId/review", element: <ReviewPage /> },
          { path: "reviews", element: <ReviewQueuePage /> },
          { path: "certificates", element: <CertificatesPage /> },
          { path: "certificates/:certificateId", element: <CertificateDetailPage /> },
          { path: "support", element: <SupportPage /> },
          { path: "support/:ticketId", element: <SupportTicketPage /> },
          { path: "monitoring", element: <MonitoringPage /> },
          { path: "sync", element: <SyncPage /> },
          { path: "notifications", element: <NotificationsPage /> },
          { path: "operations", element: <OperationsPage /> },
          { path: "reports", element: <ReportsPage /> },
          { path: "audit", element: <AuditPage /> },
          { path: "team", element: <TeamPage /> },
          { path: "settings", element: <SettingsPage /> },
          { path: "integrations", element: <IntegrationsPage /> },
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
