import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { applicationsQuery, type ApplicationStatus } from "../../api/applications";
import { ProblemNotice } from "../../app/ProblemNotice";
import { useSession } from "../identity/useSession";
import { t } from "../../locales";

const STATUSES: ApplicationStatus[] = [
  "DRAFT",
  "SUBMITTED",
  "SCRUTINY",
  "INFO_REQUIRED",
  "INSPECTION_PENDING",
  "REVIEW_PENDING",
  "COMPLIANCE_PENDING",
  "APPROVED_PENDING_ISSUE",
  "COMPLETED",
  "REJECTED",
  "WITHDRAWN",
];
const FIELD = "min-h-11 rounded-md border border-border bg-canvas px-3 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover";

/** UI-05: scoped application list with URL-synced search/status filters and cursor paging.
 *  DRAFT rows offer Continue; nothing here issues or decides anything. */
export function ApplicationsListPage() {
  const [params, setParams] = useSearchParams();
  const { principal } = useSession();
  const status = params.get("status") ?? "";
  const q = params.get("q") ?? "";
  const cursor = params.get("cursor") ?? "";
  const [search, setSearch] = useState(q);
  const searchId = useId();
  const statusId = useId();
  const query = useQuery(applicationsQuery({ status: status || undefined, q: q || undefined, cursor: cursor || undefined }));

  // Search updates the URL after a 300 ms debounce (UI-05).
  useEffect(() => {
    const handle = window.setTimeout(() => {
      if (search === q) return;
      const next = new URLSearchParams(params);
      if (search) next.set("q", search);
      else next.delete("q");
      next.delete("cursor");
      setParams(next, { replace: true });
    }, 300);
    return () => window.clearTimeout(handle);
  }, [search, q, params, setParams]);

  const canCreate = principal?.kind === "APPLICANT";
  const items = query.data?.items ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-ink">{t("applications.title")}</h1>
          <p className="mt-1 text-sm text-muted">{t("applications.subtitle")}</p>
        </div>
        {canCreate ? (
          <Link to="/applications/new" className={BUTTON}>
            {t("applications.new")}
          </Link>
        ) : null}
      </div>
      <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => e.preventDefault()} role="search">
        <div className="flex flex-col">
          <label htmlFor={searchId} className="text-sm font-medium">{t("applications.search")}</label>
          <input id={searchId} type="search" className={FIELD} value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div className="flex flex-col">
          <label htmlFor={statusId} className="text-sm font-medium">{t("applications.status")}</label>
          <select
            id={statusId}
            className={FIELD}
            value={status}
            onChange={(e) => {
              const next = new URLSearchParams(params);
              if (e.target.value) next.set("status", e.target.value);
              else next.delete("status");
              next.delete("cursor");
              setParams(next);
            }}
          >
            <option value="">{t("applications.anyStatus")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
        {status || q ? (
          <button type="button" className="min-h-11 rounded-md border border-border px-3 text-sm" onClick={() => { setSearch(""); setParams({}); }}>
            {t("applications.clearFilters")}
          </button>
        ) : null}
      </form>

      {query.isPending ? (
        <ul aria-busy="true" className="flex flex-col gap-2">
          {[0, 1, 2].map((i) => (
            <li key={i} className="h-12 animate-pulse rounded-md bg-surface" />
          ))}
        </ul>
      ) : null}
      {query.isError ? (
        <div className="flex flex-col gap-2">
          <ProblemNotice error={query.error} />
          <button type="button" className="self-start min-h-11 rounded-md border border-border px-3 text-sm" onClick={() => void query.refetch()}>
            {t("applications.retry")}
          </button>
        </div>
      ) : null}
      {query.data && items.length === 0 ? (
        <p className="text-sm text-muted">{status || q ? t("applications.noResults") : t("applications.empty")}</p>
      ) : null}
      {items.length > 0 ? (
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-muted">
              <th scope="col" className="py-2">{t("applications.col.reference")}</th>
              <th scope="col" className="py-2">{t("applications.col.premises")}</th>
              <th scope="col" className="py-2">{t("applications.col.status")}</th>
              <th scope="col" className="py-2">{t("applications.col.unit")}</th>
              <th scope="col" className="py-2">{t("applications.col.updated")}</th>
              <th scope="col" className="py-2"><span className="sr-only">{t("applications.col.actions")}</span></th>
            </tr>
          </thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.application_id} className="border-t border-border">
                <td className="py-2 font-medium">
                  <Link to={`/applications/${a.application_id}`} className="text-primary">{a.public_reference ?? a.draft_reference}</Link>
                </td>
                <td className="py-2">{a.premises.display_name} · {a.premises.category_key}</td>
                <td className="py-2">{a.status}</td>
                <td className="py-2">{a.owner_queue}</td>
                <td className="py-2">{new Date(a.updated_at).toLocaleString()}</td>
                <td className="py-2 text-right">
                  {a.status === "DRAFT" && canCreate ? (
                    <Link to={`/applications/${a.application_id}/edit`} className="text-primary">{t("applications.continue")}</Link>
                  ) : (
                    <Link to={`/applications/${a.application_id}`} className="text-primary">{t("applications.view")}</Link>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {query.data?.has_more && query.data.next_cursor ? (
        <button
          type="button"
          className="self-start min-h-11 rounded-md border border-border px-3 text-sm"
          onClick={() => {
            const next = new URLSearchParams(params);
            next.set("cursor", query.data.next_cursor ?? "");
            setParams(next);
          }}
        >
          {t("applications.nextPage")}
        </button>
      ) : null}
    </div>
  );
}
