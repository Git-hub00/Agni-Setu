import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { overviewQuery } from "../../api/cases";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t, type MessageKey } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-4 shadow-[var(--shadow-card)]";

/** UI-09: role-specific counts from the same scoped population and cutoff as the list; KPI
 *  cards link to UI-05 with the exact filter applied. Failure keeps prior data visibly stale. */
export function OverviewPage() {
  const query = useQuery(overviewQuery);
  const data = query.data;
  const cards: { key: MessageKey; value: number | undefined; to: string }[] = data
    ? data.role === "applicant"
      ? [
          { key: "overview.drafts", value: data.counts.drafts, to: "/applications?status=DRAFT" },
          { key: "overview.open", value: data.counts.open, to: "/applications" },
          { key: "overview.actionRequired", value: data.counts.action_required, to: "/applications?status=INFO_REQUIRED" },
        ]
      : [
          { key: "overview.received", value: data.counts.received, to: "/applications" },
          { key: "overview.dueSoon", value: data.counts.due_soon, to: "/applications" },
          { key: "overview.overdue", value: data.counts.overdue, to: "/applications" },
          { key: "overview.reviewWaiting", value: data.counts.review_waiting, to: "/applications?status=REVIEW_PENDING" },
          { key: "overview.routingExceptions", value: data.counts.routing_exceptions, to: "/applications?status=SUBMITTED" },
        ]
    : [];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-ink">{t("overview.title")}</h1>
        <div className="flex items-center gap-3 text-sm text-muted">
          {data ? <span>{t("overview.asOf")} {new Date(data.as_of).toLocaleTimeString()}</span> : null}
          {query.isError && data ? <span className="rounded-md bg-warning-soft px-2 py-0.5 text-warning">{t("overview.stale")}</span> : null}
          <button type="button" className="min-h-11 rounded-md border border-border px-3" onClick={() => void query.refetch()}>{t("overview.refresh")}</button>
        </div>
      </div>
      {query.isPending ? <p className="text-sm text-muted">{t("overview.loading")}</p> : null}
      {query.isError && !data ? <ProblemNotice error={query.error} /> : null}
      {data ? (
        <>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {cards.map((c) => (
              <li key={c.key}>
                <Link to={c.to} className={`${CARD} block no-underline`}>
                  <p className="text-xs uppercase tracking-wide text-muted">{t(c.key)}</p>
                  <p className="mt-1 text-2xl font-semibold text-ink">{c.value ?? 0}</p>
                </Link>
              </li>
            ))}
          </ul>
          {data.priority && data.priority.length > 0 ? (
            <section className={CARD} aria-labelledby="overview-priority">
              <h2 id="overview-priority" className="text-base font-semibold">{t("overview.priority")}</h2>
              <ul className="mt-2 text-sm">
                {data.priority.map((p) => (
                  <li key={`${p.application_id}:${p.kind}`}>
                    <Link to={`/applications/${p.application_id}`} className="text-primary">{p.public_reference ?? p.application_id.slice(0, 8)}</Link> · {p.kind} · {p.due_at ? new Date(p.due_at).toLocaleString() : t("overview.noDue")} · {p.owner_queue}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          <section className={CARD} aria-labelledby="overview-events">
            <h2 id="overview-events" className="text-base font-semibold">{t("overview.latest")}</h2>
            {data.latest_events.length === 0 ? <p className="mt-2 text-sm text-muted">{t("overview.noEvents")}</p> : null}
            <ul className="mt-2 text-sm">
              {data.latest_events.map((e) => (
                <li key={e.event_id}>
                  {new Date(e.occurred_at).toLocaleString()} · <Link to={`/applications/${e.application_id}`} className="text-primary">{e.public_reference ?? e.application_id.slice(0, 8)}</Link> · {e.event_type}
                </li>
              ))}
            </ul>
          </section>
        </>
      ) : null}
    </div>
  );
}
