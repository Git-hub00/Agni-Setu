import { Link, Outlet } from "react-router";

import type { Workspace } from "../../api/auth";
import { useSession } from "../../features/identity/useSession";
import { t, type MessageKey } from "../../locales";

/** The seven workspaces (scope 00, UI spec s.3). Routes are mounted per phase; until then the
 *  entries are visibly disabled placeholders, never dead links. Signed-in users see only the
 *  workspaces actually granted to them (UI spec s.3). */
export const WORKSPACE_KEYS: readonly MessageKey[] = [
  "workspace.applicant",
  "workspace.officer",
  "workspace.supervisor",
  "workspace.leadership",
  "workspace.admin",
  "workspace.policy",
  "workspace.public",
];

const WORKSPACE_LABEL: Record<Workspace, MessageKey> = {
  applicant: "workspace.applicant",
  officer: "workspace.officer",
  supervisor: "workspace.supervisor",
  leadership: "workspace.leadership",
  admin: "workspace.admin",
  policy: "workspace.policy",
  public: "workspace.public",
};

/** Workspaces with a mounted route (B04: applicant premises, policy governance). Admins share
 *  the policy route because they prepare drafts there; approval stays with the approver. */
const WORKSPACE_ROUTE: Partial<Record<Workspace, string>> = {
  applicant: "/overview",
  officer: "/inspections",
  supervisor: "/overview",
  leadership: "/overview",
  policy: "/policy",
  admin: "/policy",
};

export function AppShell() {
  const { principal } = useSession();
  const navKeys: readonly MessageKey[] = principal
    ? [...principal.workspaces.map((w) => WORKSPACE_LABEL[w]), "workspace.public"]
    : WORKSPACE_KEYS;
  const routeFor = (key: MessageKey): string | undefined => {
    if (!principal) return undefined;
    const workspace = (Object.keys(WORKSPACE_LABEL) as Workspace[]).find((w) => WORKSPACE_LABEL[w] === key);
    return workspace && principal.workspaces.includes(workspace) ? WORKSPACE_ROUTE[workspace] : undefined;
  };

  return (
    <div className="min-h-screen bg-canvas text-ink">
      <a href="#main-content" className="skip-link">
        {t("app.skipToContent")}
      </a>

      <header className="flex min-h-16 items-center justify-between gap-4 border-b border-border bg-surface px-4 md:px-8">
        <Link to="/" className="flex min-h-11 items-center gap-2 text-lg font-semibold text-ink no-underline">
          <span aria-hidden="true" className="inline-block size-3 rounded-full bg-primary" />
          {t("app.name")}
        </Link>
        <nav aria-label={t("nav.account")} className="flex items-center gap-3 text-sm">
          {principal ? (
            <Link to="/account" className="inline-flex min-h-11 items-center rounded-md px-3 text-ink hover:bg-canvas">
              {principal.display_name}
            </Link>
          ) : (
            <Link to="/sign-in" className="inline-flex min-h-11 items-center rounded-md border border-primary px-3 font-medium text-primary hover:bg-primary-soft">
              {t("nav.signIn")}
            </Link>
          )}
        </nav>
      </header>

      <div className="mx-auto flex w-full max-w-[1560px] flex-col gap-6 p-4 md:flex-row md:p-8">
        <nav aria-label={t("nav.workspaces")} className="md:w-[var(--sidebar-width)] md:shrink-0">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{t("nav.workspaces")}</h2>
          <ul className="flex flex-col gap-1 rounded-[var(--radius-card)] border border-border bg-surface p-2 shadow-[var(--shadow-card)]">
            {navKeys.map((key) => {
              const route = routeFor(key);
              return (
                <li key={key}>
                  {route ? (
                    <Link to={route} className="flex min-h-11 items-center rounded-md px-3 text-sm font-medium text-ink no-underline hover:bg-canvas">
                      {t(key)}
                    </Link>
                  ) : (
                    <span aria-disabled="true" className="flex min-h-11 flex-col justify-center rounded-md px-3 text-sm text-muted">
                      <span className="font-medium text-ink/70">{t(key)}</span>
                      <span className="text-xs">{t("nav.comingLater")}</span>
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </nav>

        <main id="main-content" tabIndex={-1} className="min-w-0 flex-1 outline-none">
          <Outlet />
        </main>
      </div>

      <footer className="border-t border-border bg-surface px-4 py-4 text-sm text-muted md:px-8">
        <p>
          <span className="mr-2 inline-block rounded-md bg-warning-soft px-2 py-0.5 font-medium text-warning">
            {t("app.modeLabel")}: {principal?.feature_gates.service_mode ?? "DEMO"}
          </span>
          {t("app.demoNotice")}
        </p>
      </footer>
    </div>
  );
}
