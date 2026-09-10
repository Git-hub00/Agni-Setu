import { Link, Outlet } from "react-router";

import { t, type MessageKey } from "../../locales";

/** The seven workspaces (scope 00, UI spec s.3). Routes are mounted per phase; until then the
 *  entries are visibly disabled placeholders, never dead links. */
export const WORKSPACE_KEYS: readonly MessageKey[] = [
  "workspace.applicant",
  "workspace.officer",
  "workspace.supervisor",
  "workspace.leadership",
  "workspace.admin",
  "workspace.policy",
  "workspace.public",
];

export function AppShell() {
  return (
    <div className="min-h-screen bg-canvas text-ink">
      <a href="#main-content" className="skip-link">
        {t("app.skipToContent")}
      </a>

      <header className="flex min-h-16 items-center justify-between border-b border-border bg-surface px-4 md:px-8">
        <Link to="/" className="flex min-h-11 items-center gap-2 text-lg font-semibold text-ink no-underline">
          <span aria-hidden="true" className="inline-block size-3 rounded-full bg-primary" />
          {t("app.name")}
        </Link>
        <span className="text-sm text-muted">{t("app.tagline")}</span>
      </header>

      <div className="mx-auto flex w-full max-w-[1560px] flex-col gap-6 p-4 md:flex-row md:p-8">
        <nav aria-label={t("nav.workspaces")} className="md:w-[var(--sidebar-width)] md:shrink-0">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{t("nav.workspaces")}</h2>
          <ul className="flex flex-col gap-1 rounded-[var(--radius-card)] border border-border bg-surface p-2 shadow-[var(--shadow-card)]">
            {WORKSPACE_KEYS.map((key) => (
              <li key={key}>
                <span
                  aria-disabled="true"
                  className="flex min-h-11 flex-col justify-center rounded-md px-3 text-sm text-muted"
                >
                  <span className="font-medium text-ink/70">{t(key)}</span>
                  <span className="text-xs">{t("nav.comingLater")}</span>
                </span>
              </li>
            ))}
          </ul>
        </nav>

        <main id="main-content" tabIndex={-1} className="min-w-0 flex-1 outline-none">
          <Outlet />
        </main>
      </div>

      <footer className="border-t border-border bg-surface px-4 py-4 text-sm text-muted md:px-8">
        <p>
          <span className="mr-2 inline-block rounded-md bg-warning-soft px-2 py-0.5 font-medium text-warning">
            {t("app.modeLabel")}: DEMO
          </span>
          {t("app.demoNotice")}
        </p>
      </footer>
    </div>
  );
}
