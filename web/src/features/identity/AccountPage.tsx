import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";

import { t } from "../../locales";
import { unsentWork } from "../../offline/database";
import { useSession, useSignOut } from "./useSession";

/** UI-03: account facts from the server projection, sign out. Contact change and
 * delegations arrive with their phases; no dead controls are shown. */
export function AccountPage() {
  const { principal } = useSession();
  const signOut = useSignOut();
  const navigate = useNavigate();
  // Unsent offline work is a warning, never a blocker (docs/09 s.9); storage errors read as "none".
  const unsent = useQuery({
    queryKey: ["offline", "unsent", principal?.id ?? ""] as const,
    queryFn: () => unsentWork(principal?.id ?? "").catch(() => ({ drafts: 0, operations: 0, files: 0 })),
    enabled: principal !== null && principal.kind === "STAFF",
    retry: false,
  });
  const pending = unsent.data && unsent.data.operations + unsent.data.drafts + unsent.data.files > 0 ? unsent.data : null;

  if (!principal) {
    return null; // RequireSession guarantees a principal; defensive for direct renders
  }

  const onSignOut = () => {
    signOut.mutate(undefined, {
      onSettled: () => {
        void navigate("/sign-in", { replace: true });
      },
    });
  };

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold text-ink">{t("account.title")}</h1>
      <section aria-labelledby="account-identity" className="rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]">
        <h2 id="account-identity" className="text-base font-semibold text-ink">{t("account.identity")}</h2>
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-muted">{t("account.displayName")}</dt>
          <dd>{principal.display_name}</dd>
          <dt className="text-muted">{t("account.kind")}</dt>
          <dd>{principal.kind}</dd>
          <dt className="text-muted">{t("account.workspaces")}</dt>
          <dd>{principal.workspaces.length ? principal.workspaces.join(", ") : t("account.noWorkspaces")}</dd>
          <dt className="text-muted">{t("account.sessionExpires")}</dt>
          <dd>{principal.session_expires_at ? new Date(principal.session_expires_at).toLocaleString() : "-"}</dd>
        </dl>
        <p className="mt-3 inline-block rounded-md bg-information-soft px-2 py-1 text-xs text-information">
          {principal.kind === "APPLICANT" ? t("account.contactVerified") : t("account.staffIdentity")}
        </p>
      </section>
      <section aria-labelledby="account-delegations" className="rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]">
        <h2 id="account-delegations" className="text-base font-semibold text-ink">{t("account.delegations")}</h2>
        <p className="mt-2 text-sm text-muted">{t("account.delegationsLater")}</p>
      </section>
      <div className="flex flex-col gap-3">
        {pending ? (
          <p role="status" className="rounded-md bg-warning-soft p-3 text-sm text-warning">
            {t("account.unsentWork")} {pending.operations} {t("account.unsentOperations")}, {pending.drafts} {t("account.unsentDrafts")}, {pending.files} {t("account.unsentFiles")}. {t("account.unsentKept")}
          </p>
        ) : null}
        <button type="button" onClick={onSignOut} disabled={signOut.isPending} className="inline-flex min-h-11 items-center self-start rounded-md border border-border bg-surface px-4 font-medium text-ink hover:bg-canvas disabled:opacity-60">
          {signOut.isPending ? t("account.signingOut") : t("account.signOut")}
        </button>
      </div>
    </div>
  );
}
