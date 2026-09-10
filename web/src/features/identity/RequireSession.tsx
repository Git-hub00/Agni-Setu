import { Navigate, Outlet, useLocation } from "react-router";

import { t } from "../../locales";
import { useSession } from "./useSession";

/** Route-level guard (security s.4): redirects anonymous visitors to sign-in with a safe return
 * path. The backend scope check remains the enforcement boundary. */
export function RequireSession() {
  const { principal, isLoading, isError } = useSession();
  const location = useLocation();

  if (isLoading) {
    return <p aria-live="polite" className="text-muted">{t("session.checking")}</p>;
  }
  if (isError) {
    return <p role="alert" className="text-danger">{t("home.apiError")}</p>;
  }
  if (!principal) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/sign-in?next=${next}`} replace />;
  }
  return <Outlet />;
}
