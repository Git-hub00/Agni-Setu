import { Link } from "react-router";

import { t } from "../locales";

export function NotFoundPage() {
  return (
    <section aria-labelledby="not-found-heading">
      <h1 id="not-found-heading" className="text-2xl font-semibold text-ink">
        {t("notFound.title")}
      </h1>
      <p className="mt-2 text-muted">{t("notFound.body")}</p>
      <Link to="/" className="mt-6 inline-flex min-h-11 items-center rounded-md bg-primary px-4 text-white hover:bg-primary-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">
        {t("nav.home")}
      </Link>
    </section>
  );
}
