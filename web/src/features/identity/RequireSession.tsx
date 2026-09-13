import { Navigate, Outlet, useLocation } from "react-router";

import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";
import { useSession } from "./useSession";

/** Route-level guard (security s.4): redirects anonymous visitors to sign-in with a safe return
 * path. The backend scope check remains the enforcement boundary.
 *
 * A failed bootstrap (network loss, or a 503 problem with Retry-After) is shown as the problem
 * it is and can be retried in place: the shell must never leave the user on a dead end that only
 * a manual reload could resolve (found by the production-readiness regression, DEF-013). */
export function RequireSession() {
  const { principal, isLoading, isError, error, refetch } = useSession();
  const location = useLocation();

  if (isLoading) {
    return <p aria-live="polite" className="text-muted">{t("session.checking")}</p>;
  }
  if (isError) {
    return (
      <div className="flex flex-col gap-3">
        <ProblemNotice error={error} />
        <button
          type="button"
          className="self-start min-h-11 rounded-md border border-border px-3 text-sm"
          onClick={() => void refetch()}
        >
          {t("session.retry")}
        </button>
      </div>
    );
  }
  if (!principal) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/sign-in?next=${next}`} replace />;
  }
  return <Outlet />;
}
