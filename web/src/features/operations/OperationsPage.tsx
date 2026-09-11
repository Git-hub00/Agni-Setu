import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router";

import { jobsQuery, reconcileJob, retryJob, type Job } from "../../api/operations";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t, type MessageKey } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-4 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 py-2 text-sm text-ink";
const STATES = ["PENDING", "RUNNING", "RETRY_WAIT", "DEAD_LETTER", "RECONCILIATION_REQUIRED", "COMPLETE"] as const;

/** UI-20: readiness of the asynchronous machinery (outbox lag, oldest due job, worker
 *  activity, dead letters, unknown outcomes), a sanitised job list and the two recovery
 *  commands. Retry resumes the same logical action; an ambiguous outcome disables blind retry
 *  and demands reconciliation. Nothing here can change a case. */
export function OperationsPage() {
  const [params, setParams] = useSearchParams();
  const state = params.get("state");
  const query = useQuery(jobsQuery(state ? [state] : []));
  const data = query.data;
  const kpis: { key: MessageKey; value: string | number; warn?: boolean }[] = data
    ? [
        { key: "operations.outboxPending", value: data.summary.outbox.pending, warn: data.summary.outbox.pending > 0 && data.summary.outbox.oldest_pending_seconds > 300 },
        { key: "operations.oldestDue", value: `${data.summary.oldest_due_seconds}s`, warn: data.summary.oldest_due_seconds > 300 },
        { key: "operations.worker", value: data.summary.worker_heartbeat_ok ? t("operations.workerOk") : t("operations.workerStale"), warn: !data.summary.worker_heartbeat_ok },
        { key: "operations.deadLetter", value: data.summary.dead_letter, warn: data.summary.dead_letter > 0 },
        { key: "operations.reconcile", value: data.summary.reconciliation_required, warn: data.summary.reconciliation_required > 0 },
        { key: "operations.retryWait", value: data.summary.retry_wait },
      ]
    : [];
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-ink">{t("operations.title")}</h1>
        <div className="flex items-center gap-3 text-sm text-muted">
          {data ? <span>{t("overview.asOf")} {new Date(data.summary.as_of).toLocaleTimeString()}</span> : null}
          <button type="button" className="min-h-11 rounded-md border border-border px-3" onClick={() => void query.refetch()}>{t("overview.refresh")}</button>
        </div>
      </div>
      <p className="text-sm text-muted">{t("operations.help")}</p>
      {query.isPending ? <p className="text-sm text-muted">{t("operations.loading")}</p> : null}
      {query.isError ? <ProblemNotice error={query.error} /> : null}
      {data ? (
        <ul className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {kpis.map((k) => (
            <li key={k.key} className={`${CARD} ${k.warn ? "border-warning" : ""}`}>
              <p className="text-xs uppercase tracking-wide text-muted">{t(k.key)}</p>
              <p className={`mt-1 text-xl font-semibold ${k.warn ? "text-warning" : "text-ink"}`}>{k.value}</p>
            </li>
          ))}
        </ul>
      ) : null}
      <nav aria-label={t("operations.stateFilter")} className="flex flex-wrap gap-2">
        <button type="button" aria-pressed={!state} className={`min-h-11 rounded-md px-3 text-sm ${!state ? "bg-primary text-white" : "border border-border bg-surface text-ink"}`} onClick={() => setParams({})}>{t("monitoring.all")}</button>
        {STATES.map((s) => (
          <button key={s} type="button" aria-pressed={state === s} className={`min-h-11 rounded-md px-3 text-sm ${state === s ? "bg-primary text-white" : "border border-border bg-surface text-ink"}`} onClick={() => setParams({ state: s })}>
            {s}
          </button>
        ))}
      </nav>
      {data ? (
        <div className={`${CARD} overflow-x-auto`}>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-muted">
                <th className="py-1">{t("operations.kind")}</th>
                <th className="py-1">{t("operations.state")}</th>
                <th className="py-1">{t("operations.attempts")}</th>
                <th className="py-1">{t("operations.next")}</th>
                <th className="py-1">{t("operations.error")}</th>
                <th className="py-1">{t("operations.action")}</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((j) => (
                <JobRow key={j.job_id} job={j} />
              ))}
            </tbody>
          </table>
          {data.items.length === 0 ? <p className="mt-2 text-sm text-muted">{t("operations.empty")}</p> : null}
          <p className="mt-3 text-xs text-muted">{t("operations.recoveryHint")}</p>
        </div>
      ) : null}
    </div>
  );
}

function JobRow({ job }: { job: Job }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const action = job.next_permitted_action;
  const recover = useMutation({
    mutationFn: () => (action === "RETRY" ? retryJob(job.job_id, reason.trim()) : reconcileJob(job.job_id, reason.trim())),
    onSuccess: async () => {
      setOpen(false);
      setReason("");
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  return (
    <>
      <tr className="border-t border-border align-top">
        <td className="py-1">
          <span className="font-medium">{job.kind}</span>
          <span className="block text-xs text-muted">{job.logical_action_id.slice(0, 8)}</span>
        </td>
        <td className="py-1">{job.state}{job.disposition ? ` · ${job.disposition}` : ""}</td>
        <td className="py-1">{job.attempt_count}/{job.max_attempts}</td>
        <td className="py-1">{job.next_attempt_at ? new Date(job.next_attempt_at).toLocaleString() : "-"}</td>
        <td className="py-1">{job.last_error_code ?? "-"}</td>
        <td className="py-1">
          {action ? (
            <button type="button" className="min-h-11 rounded-md border border-border px-3 text-sm" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
              {t(`operations.next.${action}` as MessageKey)}
            </button>
          ) : (
            <span className="text-muted">-</span>
          )}
        </td>
      </tr>
      {open && action ? (
        <tr className="border-t border-border bg-canvas">
          <td colSpan={6} className="p-3">
            <form
              className="flex flex-wrap items-end gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                recover.mutate();
              }}
            >
              <label className="flex-1 text-sm font-medium">
                {t("operations.reason")}
                <input className={FIELD} minLength={10} maxLength={4000} value={reason} onChange={(e) => setReason(e.target.value)} />
              </label>
              <button type="submit" className="inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white disabled:opacity-60" disabled={recover.isPending || reason.trim().length < 10}>
                {action === "RETRY" ? t("operations.confirmRetry") : t("operations.confirmReconcile")}
              </button>
              <p className="w-full text-xs text-muted">{action === "RETRY" ? t("operations.retryHint") : t("operations.reconcileHint")}</p>
              {recover.isError ? <div className="w-full"><ProblemNotice error={recover.error} /></div> : null}
            </form>
          </td>
        </tr>
      ) : null}
    </>
  );
}
