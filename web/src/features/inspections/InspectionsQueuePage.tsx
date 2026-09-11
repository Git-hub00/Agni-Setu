import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";

import { inspectionsQuery, type Inspection } from "../../api/inspections";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t, type MessageKey } from "../../locales";

const FILTERS: { key: string; label: MessageKey; states?: string[]; unassigned?: boolean }[] = [
  { key: "today", label: "queue.today", states: ["SCHEDULED", "IN_PROGRESS"] },
  { key: "upcoming", label: "queue.upcoming", states: ["SCHEDULED"] },
  { key: "unassigned", label: "queue.unassigned", states: ["REQUESTED"], unassigned: true },
  { key: "closed", label: "queue.closed", states: ["COMPLETED", "FAILED", "CANCELLED"] },
  { key: "all", label: "queue.all" },
];
const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-4 shadow-[var(--shadow-card)]";

function isToday(iso: string | null): boolean {
  if (!iso) return false;
  const d = new Date(iso);
  const now = new Date();
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
}

/** UI-10: the officer's assigned attempts or the supervisor's jurisdiction queue as large touch
 *  cards. Filter state lives in the URL. Conflicts and unavailability are surfaced elsewhere as
 *  actionable errors, never hidden here. */
export function InspectionsQueuePage() {
  const [params, setParams] = useSearchParams();
  const filterKey = params.get("filter") ?? "all";
  const filter = FILTERS.find((f) => f.key === filterKey) ?? FILTERS[FILTERS.length - 1];
  const query = useQuery(inspectionsQuery({ state: filter.states, unassigned: filter.unassigned }));
  const items = (query.data?.items ?? []).filter((i) => (filter.key === "today" ? isToday(i.scheduled_start) : true));
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-ink">{t("queue.title")}</h1>
        <Link to="/schedule" className="text-sm text-primary">{t("queue.openSchedule")}</Link>
      </div>
      <nav aria-label={t("queue.filters")} className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            aria-pressed={f.key === filter.key}
            className={`min-h-11 rounded-md px-3 text-sm ${f.key === filter.key ? "bg-primary text-white" : "border border-border bg-surface text-ink"}`}
            onClick={() => setParams({ filter: f.key })}
          >
            {t(f.label)}
          </button>
        ))}
      </nav>
      {query.isPending ? <p className="text-sm text-muted">{t("queue.loading")}</p> : null}
      {query.isError ? <ProblemNotice error={query.error} /> : null}
      {query.data && items.length === 0 ? <p className="text-sm text-muted">{t("queue.empty")}</p> : null}
      <ul className="grid gap-3 md:grid-cols-2">
        {items.map((i) => (
          <li key={i.inspection_id}>
            <InspectionCard inspection={i} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function InspectionCard({ inspection }: { inspection: Inspection }) {
  return (
    <Link to={`/inspections/${inspection.inspection_id}`} className={`${CARD} block no-underline`} data-status={inspection.status}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted">{inspection.public_reference ?? inspection.application_id.slice(0, 8)} · {t("queue.attempt")} {inspection.attempt_number}</p>
          <p className="mt-1 text-base font-semibold text-ink">{inspection.premises.display_name}</p>
          <p className="text-sm text-muted">{inspection.premises.locality} · {inspection.premises.category_key} · {inspection.purpose}</p>
        </div>
        <span className="rounded-md bg-canvas px-2 py-0.5 text-xs font-medium text-ink">{inspection.status}</span>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted">{t("queue.appointment")}</dt>
        <dd>{inspection.scheduled_start ? `${new Date(inspection.scheduled_start).toLocaleString()} (${inspection.appointment_timezone})` : t("queue.notScheduled")}</dd>
        <dt className="text-muted">{t("queue.assignment")}</dt>
        <dd>{inspection.current_assignment ? `${inspection.current_assignment.officer_name} · v${inspection.current_assignment.number}` : t("queue.unassignedLabel")}</dd>
        <dt className="text-muted">{t("queue.checklist")}</dt>
        <dd>{inspection.checklist_ref}</dd>
      </dl>
    </Link>
  );
}
