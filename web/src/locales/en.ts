/**
 * English copy. Every visible string goes through `t()` (engineering standards s.3). Hindi
 * (`hi.ts`) is added only after reviewed translations exist; identifiers, stored dates and policy
 * semantics never change with locale.
 */
export const en = {
  "app.name": "Agni Setu",
  "app.tagline": "Fire safety certificate case management",
  "app.skipToContent": "Skip to main content",
  "app.demoNotice": "Demonstration build - not an official government service",
  "app.modeLabel": "Service mode",

  "nav.home": "Home",
  "nav.workspaces": "Workspaces",
  "nav.comingLater": "coming in a later phase",

  "workspace.applicant": "Applicant",
  "workspace.officer": "Field officer",
  "workspace.supervisor": "Supervisor",
  "workspace.leadership": "Leadership",
  "workspace.admin": "Administration",
  "workspace.policy": "Policy approver",
  "workspace.public": "Public verification",

  "home.title": "Development build",
  "home.body":
    "This is the runnable skeleton of Agni Setu. Application features arrive phase by phase; nothing here issues, approves or verifies a real certificate.",
  "home.apiStatus": "API readiness",
  "home.apiLoading": "Checking the API...",
  "home.apiReady": "API is ready",
  "home.apiNotReady": "API is not ready",
  "home.apiError": "The API could not be reached",
  "home.apiCheck.database": "Database",
  "home.apiCheck.schema": "Schema",
  "home.apiCheck.configuration": "Configuration",
  "home.check.pass": "pass",
  "home.check.fail": "fail",
  "home.refresh": "Refresh status",

  "notFound.title": "Page not found",
  "notFound.body": "The address does not match any page you can open. Use the link below to return to a page you are authorised to see.",
  "error.title": "Something went wrong",
  "error.body": "The page could not be shown. Your work on the server is unaffected; try again from the home page.",
} as const;

export type MessageKey = keyof typeof en;
