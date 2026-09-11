import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { FIELD_SETS, createExport, exportsQuery, metricsQuery, requestExportAccess, type ExportJob, type ExportKind, type MetricsFilters } from "../../api/reporting";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t, type MessageKey } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 py-2 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";
const GHOST = "inline-flex min-h-11 items-center rounded-md border border-border px-3 font-medium text-ink disabled:opacity-60";

type CountKey = "received" | "open" | "completed" | "rejected" | "withdrawn" | "published_certificates" | "overdue_obligations";
const COUNT_KEYS: CountKey[] = ["received", "open", "completed", "rejected", "withdrawn", "published_certificates", "overdue_obligations"];
const METRIC_LABEL: Record<CountKey, MessageKey> = {
  received: "reports.metric.received",
  open: "reports.metric.open",
  completed: "reports.metric.completed",
  rejected: "reports.metric.rejected",
  withdrawn: "reports.metric.withdrawn",
  published_certificates: "reports.metric.published_certificates",
  overdue_obligations: "reports.metric.overdue_obligations",
};

const KINDS: ExportKind[] = ["CASES", "CERTIFICATES", "REPORT", "AUDIT"];

function hours(value: number | null): string {
  return value === null ? "-" : `${value.toFixed(1)} h`;
}

/** UI-22: one cutoff, one scope, definitions beside every figure, and the controlled export
 *  flow (purpose, frozen scope, asynchronous generation, ticketed download, expiry). */
export function ReportsPage() {
  const [filters, setFilters] = useState<MetricsFilters>({});
  const [draft, setDraft] = useState<MetricsFilters>({});
  const metrics = useQuery(metricsQuery(filters));
  const exports = useQuery({ ...exportsQuery, refetchInterval: (query) => (query.state.data?.items.some((e) => e.state === "READY" || e.state === "RUNNING") ? 5000 : false) });
  const ids = { category: useId(), from: useId(), to: useId(), asOf: useId() };
  const data = metrics.data;
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-ink">{t("reports.title")}</h1>
        <p className="mt-1 max-w-prose text-sm text-muted">{t("reports.help")}</p>
      </div>
      <form
        className={`${CARD} grid gap-3 sm:grid-cols-4`}
        aria-label={t("reports.filters")}
        onSubmit={(e) => {
          e.preventDefault();
          setFilters(draft);
        }}
      >
        <div>
          <label htmlFor={ids.category} className="text-sm font-medium">{t("reports.category")}</label>
          <input id={ids.category} className={FIELD} value={draft.category_key ?? ""} onChange={(e) => setDraft({ ...draft, category_key: e.target.value || undefined })} />
        </div>
        <div>
          <label htmlFor={ids.from} className="text-sm font-medium">{t("reports.submittedFrom")}</label>
          <input id={ids.from} type="datetime-local" className={FIELD} onChange={(e) => setDraft({ ...draft, submitted_from: e.target.value ? new Date(e.target.value).toISOString() : undefined })} />
        </div>
        <div>
          <label htmlFor={ids.to} className="text-sm font-medium">{t("reports.submittedTo")}</label>
          <input id={ids.to} type="datetime-local" className={FIELD} onChange={(e) => setDraft({ ...draft, submitted_to: e.target.value ? new Date(e.target.value).toISOString() : undefined })} />
        </div>
        <div>
          <label htmlFor={ids.asOf} className="text-sm font-medium">{t("reports.asOf")}</label>
          <input id={ids.asOf} type="datetime-local" className={FIELD} onChange={(e) => setDraft({ ...draft, as_of: e.target.value ? new Date(e.target.value).toISOString() : undefined })} />
        </div>
        <div className="sm:col-span-4">
          <button type="submit" className={BUTTON}>{t("reports.apply")}</button>
        </div>
      </form>
      {metrics.isPending ? <p className="text-sm text-muted">{t("reports.loading")}</p> : null}
      {metrics.isError ? <ProblemNotice error={metrics.error} /> : null}
      {data ? (
        <section className={CARD} aria-labelledby="reports-metrics">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="reports-metrics" className="text-base font-semibold">{t("reports.metricsTitle")}</h2>
            <p className="text-xs text-muted">
              {t("reports.cutoff")} {new Date(data.as_of).toLocaleString()} · {data.definition_version} · {t("reports.scope")} {data.scope.kind}
              {" · "}
              <span className={data.reconciled ? "text-positive" : "text-danger"}>{data.reconciled ? t("reports.reconciled") : t("reports.notReconciled")}</span>
            </p>
          </div>
          <dl className="mt-3 grid gap-3 sm:grid-cols-4">
            {COUNT_KEYS.map((key) => (
              <div key={key} className="rounded-md border border-border p-3">
                <dt className="text-xs uppercase tracking-wide text-muted">{t(METRIC_LABEL[key])}</dt>
                <dd className="mt-1 text-xl font-semibold text-ink">{data.metrics[key]}</dd>
                <dd className="mt-1 text-xs text-muted">{data.definitions[key]}</dd>
              </div>
            ))}
            <div className="rounded-md border border-border p-3">
              <dt className="text-xs uppercase tracking-wide text-muted">{t("reports.metric.resolution")}</dt>
              <dd className="mt-1 text-sm text-ink">
                {t("reports.median")} {hours(data.metrics.resolution_hours.median)} · P90 {hours(data.metrics.resolution_hours.p90)}
              </dd>
              <dd className="mt-1 text-xs text-muted">
                {data.metrics.resolution_hours.insufficient_sample
                  ? `${t("reports.insufficientSample")} (n=${data.metrics.resolution_hours.sample_size})`
                  : `n=${data.metrics.resolution_hours.sample_size}`}
              </dd>
            </div>
          </dl>
          <h3 className="mt-4 text-sm font-semibold">{t("reports.byStatus")}</h3>
          <ul className="mt-1 flex flex-wrap gap-2 text-sm">
            {Object.entries(data.by_status).map(([status, count]) => (
              <li key={status} className="rounded-md bg-canvas px-2 py-1">{status}: {count}</li>
            ))}
            {Object.keys(data.by_status).length === 0 ? <li className="text-muted">{t("reports.noCases")}</li> : null}
          </ul>
          <p className="mt-2 text-xs text-muted">{t("reports.draftsExcluded")} {data.exclusions.drafts}</p>
        </section>
      ) : null}
      <ExportPanel filters={filters} />
      <section className={CARD} aria-labelledby="reports-exports">
        <h2 id="reports-exports" className="text-base font-semibold">{t("reports.exportsTitle")}</h2>
        {exports.isError ? <ProblemNotice error={exports.error} /> : null}
        {exports.data && exports.data.items.length === 0 ? <p className="mt-2 text-sm text-muted">{t("reports.noExports")}</p> : null}
        <ul className="mt-3 flex flex-col gap-2 text-sm">
          {(exports.data?.items ?? []).map((job) => (
            <ExportRow key={job.export_id} job={job} />
          ))}
        </ul>
      </section>
    </div>
  );
}

function ExportPanel({ filters }: { filters: MetricsFilters }) {
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<ExportKind>("CASES");
  const [purpose, setPurpose] = useState("");
  const ids = { kind: useId(), purpose: useId() };
  const create = useMutation({
    mutationFn: () => createExport({ kind, field_set_key: FIELD_SETS[kind][0] ?? "", purpose: purpose.trim(), filters }),
    onSuccess: async () => {
      setPurpose("");
      await queryClient.invalidateQueries({ queryKey: ["exports"] });
    },
  });
  return (
    <section className={CARD} aria-labelledby="reports-export">
      <h2 id="reports-export" className="text-base font-semibold">{t("reports.exportTitle")}</h2>
      <p className="mt-1 text-sm text-muted">{t("reports.exportHelp")}</p>
      <form
        className="mt-3 grid gap-3 sm:grid-cols-3"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <div>
          <label htmlFor={ids.kind} className="text-sm font-medium">{t("reports.exportKind")}</label>
          <select id={ids.kind} className={FIELD} value={kind} onChange={(e) => setKind(e.target.value as ExportKind)}>
            {KINDS.map((k) => (
              <option key={k} value={k}>{t(`reports.kind.${k}` as MessageKey)} · {FIELD_SETS[k][0]}</option>
            ))}
          </select>
        </div>
        <div className="sm:col-span-2">
          <label htmlFor={ids.purpose} className="text-sm font-medium">{t("reports.purpose")}</label>
          <input id={ids.purpose} className={FIELD} minLength={10} maxLength={500} value={purpose} onChange={(e) => setPurpose(e.target.value)} />
        </div>
        {create.isError ? <div className="sm:col-span-3"><ProblemNotice error={create.error} /></div> : null}
        <div className="sm:col-span-3">
          <button type="submit" className={BUTTON} disabled={create.isPending || purpose.trim().length < 10}>{t("reports.requestExport")}</button>
        </div>
      </form>
    </section>
  );
}

function ExportRow({ job }: { job: ExportJob }) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [open, setOpen] = useState(false);
  const access = useMutation({
    mutationFn: () => requestExportAccess(job.export_id, reason.trim()),
    onSuccess: async (granted) => {
      window.location.assign(granted.url);
      setOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["exports"] });
    },
  });
  const action = job.allowed_actions.find((a) => a.key === "access");
  const expired = job.state === "EXPIRED"; // the server flips the state on read; the list polls
  return (
    <li className="rounded-md border border-border p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-medium">
            {t(`reports.kind.${job.kind}` as MessageKey)} · {job.field_set_key}
            <span className="ml-2 rounded-md bg-canvas px-2 py-0.5 text-xs">{job.state}</span>
          </p>
          <p className="text-muted">
            {job.purpose} · {t("reports.population")} {job.population ?? "-"} · {t("reports.rows")} {job.row_count ?? "-"} · {t("reports.expires")} {new Date(job.expires_at).toLocaleString()}
          </p>
          {job.scope_valid === false ? <p className="text-danger">{t("reports.scopeChanged")}</p> : null}
          {job.last_error_code ? <p className="text-danger">{job.last_error_code}</p> : null}
        </div>
        <button type="button" className={GHOST} disabled={!action?.enabled || expired} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {expired ? t("reports.expired") : t("reports.download")}
        </button>
      </div>
      {open ? (
        <form
          className="mt-3 flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            access.mutate();
          }}
        >
          <label className="flex-1 text-sm font-medium">
            {t("reports.accessReason")}
            <input className={FIELD} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button type="submit" className={BUTTON} disabled={access.isPending}>{t("reports.confirmDownload")}</button>
          {access.isError ? <div className="w-full"><ProblemNotice error={access.error} /></div> : null}
        </form>
      ) : null}
    </li>
  );
}
