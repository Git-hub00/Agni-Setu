import { isRouteErrorResponse, Link, useRouteError } from "react-router";

import { t } from "../locales";

/** Route-level error boundary: a useful message and a way home, never a blank page (UI s.3). */
export function RouteErrorBoundary() {
  const error = useRouteError();
  const isNotFound = isRouteErrorResponse(error) && error.status === 404;

  return (
    <main id="main-content" tabIndex={-1} className="mx-auto max-w-3xl p-6" aria-labelledby="error-heading">
      <h1 id="error-heading" className="text-2xl font-semibold text-ink">
        {isNotFound ? t("notFound.title") : t("error.title")}
      </h1>
      <p className="mt-2 text-muted">{isNotFound ? t("notFound.body") : t("error.body")}</p>
      <Link to="/" className="mt-6 inline-flex min-h-11 items-center rounded-md bg-primary px-4 text-white hover:bg-primary-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">
        {t("nav.home")}
      </Link>
    </main>
  );
}
