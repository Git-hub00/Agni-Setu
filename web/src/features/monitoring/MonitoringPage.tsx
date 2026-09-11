import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { acknowledgeEscalation, createEscalation, obligationQuery, obligationsQuery, type Escalation, type ObligationRow } from "../../api/monitoring";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t, type MessageKey } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-4 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";
const SECONDARY = "inline-flex min-h-11 items-center rounded-md border border-border bg-surface px-4 font-medium text-ink hover:bg-canvas disabled:opacity-60";

const TABS: { key: string; label: MessageKey; urgency?: string; escalations?: boolean }[] = [
  { key: "due-soon", label: "monitoring.dueSoon", urgency: "DUE_SOON" },
  { key: "overdue", label: "monitoring.overdue", urgency: "OVERDUE" },
  { key: "escalations", label: "monitoring.escalations", escalations: true },
  { key: "paused", label: "monitoring.paused", urgency: "PAUSED" },
  { key: "all", label: "monitoring.all" },
];

const URGENCY_KEY: Record<ObligationRow["urgency"], MessageKey> = {
  OVERDUE: "monitoring.urgency.OVERDUE",
  DUE_SOON: "monitoring.urgency.DUE_SOON",
  ON_TRACK: "monitoring.urgency.ON_TRACK",
  PAUSED: "monitoring.urgency.PAUSED",
  NO_ESTIMATE: "monitoring.urgency.NO_ESTIMATE",
  CLOSED: "monitoring.urgency.CLOSED",
};

/** UI-15: obligations from one cutoff, tabs for due soon / overdue / escalations / paused,
 *  clock drawer per row, manual escalation and acknowledgement. Acknowledged is never
 *  resolved; paused clocks stay visible; leadership can inspect but the server refuses their
 *  interventions. */
export function MonitoringPage() {
  const [params, setParams] = useSearchParams();
  const tabKey = params.get("tab") ?? "due-soon";
  const tab = TABS.find((x) => x.key === tabKey) ?? TABS[0];
  const query = useQuery(obligationsQuery(tab.urgency ? { urgency: tab.urgency } : {}));
  const data = query.data;
  const rows = (data?.items ?? []).filter((r) => (tab.escalations ? r.open_escalations.length > 0 : true));
  const [openId, setOpenId] = useState<string | null>(null);
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-ink">{t("monitoring.title")}</h1>
        <div className="flex items-center gap-3 text-sm text-muted">
          {data ? <span>{t("overview.asOf")} {new Date(data.as_of).toLocaleTimeString()}</span> : null}
          {query.isError && data ? <span className="rounded-md bg-warning-soft px-2 py-0.5 text-warning">{t("overview.stale")}</span> : null}
          <button type="button" className="min-h-11 rounded-md border border-border px-3" onClick={() => void query.refetch()}>{t("overview.refresh")}</button>
        </div>
      </div>
      {data ? (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Kpi label="monitoring.overdue" value={data.counts.overdue} />
          <Kpi label="monitoring.dueSoon" value={data.counts.due_soon} />
          <Kpi label="monitoring.escalations" value={data.counts.open_escalations} />
          <Kpi label="monitoring.paused" value={data.counts.paused} />
        </ul>
      ) : null}
      <nav aria-label={t("monitoring.tabs")} className="flex flex-wrap gap-2">
        {TABS.map((x) => (
          <button
            key={x.key}
            type="button"
            aria-pressed={x.key === tab.key}
            className={`min-h-11 rounded-md px-3 text-sm ${x.key === tab.key ? "bg-primary text-white" : "border border-border bg-surface text-ink"}`}
            onClick={() => setParams({ tab: x.key })}
          >
            {t(x.label)}
          </button>
        ))}
      </nav>
      {query.isPending ? <p className="text-sm text-muted">{t("monitoring.loading")}</p> : null}
      {query.isError && !data ? <ProblemNotice error={query.error} /> : null}
      {data && rows.length === 0 ? <p className="text-sm text-muted">{t("monitoring.empty")}</p> : null}
      <ul className="flex flex-col gap-3">
        {rows.map((row) => (
          <li key={row.obligation_id} className={CARD}>
            <ObligationCard row={row} open={openId === row.obligation_id} onToggle={() => setOpenId(openId === row.obligation_id ? null : row.obligation_id)} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function Kpi({ label, value }: { label: MessageKey; value: number }) {
  return (
    <li className={CARD}>
      <p className="text-xs uppercase tracking-wide text-muted">{t(label)}</p>
      <p className="mt-1 text-2xl font-semibold text-ink">{value}</p>
    </li>
  );
}

function ObligationCard({ row, open, onToggle }: { row: ObligationRow; open: boolean; onToggle: () => void }) {
  const queryClient = useQueryClient();
  const detail = useQuery({ ...obligationQuery(row.obligation_id), enabled: open });
  const [reason, setReason] = useState("");
  const [nextAction, setNextAction] = useState("");
  const [level, setLevel] = useState(1);
  const ids = { reason: useId(), next: useId(), level: useId() };
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["obligations"] });
    await queryClient.invalidateQueries({ queryKey: ["notifications"] });
  };
  const escalate = useMutation({ mutationFn: () => createEscalation(row, { reason, requested_level: level, next_action: nextAction }), onSuccess: refresh });
  const acknowledge = useMutation({ mutationFn: (e: Escalation) => acknowledgeEscalation(e, { reason, next_action: nextAction || undefined }), onSuccess: refresh });
  const valid = reason.trim().length >= 10;
  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted">{row.kind.replace(/_/g, " ")} · {row.time_basis} · {row.owner_queue}</p>
          <p className="mt-1 text-base font-semibold text-ink">
            {row.public_reference ? <Link to={`/applications/${row.application_id ?? ""}`} className="text-primary">{row.public_reference}</Link> : t("monitoring.noCase")} · {row.application_status ?? "-"}
          </p>
          <p className="text-sm text-muted">
            {t("monitoring.started")} {new Date(row.started_at).toLocaleString()} · {row.due_at ? `${t("monitoring.due")} ${new Date(row.due_at).toLocaleString()}` : t("monitoring.pausedNoEstimate")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${row.urgency === "OVERDUE" ? "bg-danger-soft text-danger" : row.urgency === "DUE_SOON" ? "bg-warning-soft text-warning" : "bg-canvas text-ink"}`}>{t(URGENCY_KEY[row.urgency])}</span>
          <button type="button" className={SECONDARY} aria-expanded={open} onClick={onToggle}>{open ? t("monitoring.hideClock") : t("monitoring.showClock")}</button>
        </div>
      </div>
      {row.open_escalations.length > 0 ? (
        <ul className="mt-3 flex flex-col gap-1 text-sm">
          {row.open_escalations.map((e) => (
            <li key={e.escalation_id} className="flex flex-wrap items-center gap-3 rounded-md border border-border p-2">
              <span className="font-medium">{t("monitoring.escalationLevel")} {e.level} · {e.state}{e.manual ? ` · ${t("monitoring.manual")}` : ""}</span>
              <span className="text-muted">{e.reason}</span>
              {e.next_action ? <span className="text-muted">{t("monitoring.nextAction")} {e.next_action}</span> : null}
              {e.state === "OPEN" ? (
                <button type="button" className={SECONDARY} disabled={!valid || acknowledge.isPending} onClick={() => acknowledge.mutate(e)}>{t("monitoring.acknowledge")}</button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {open ? (
        <div className="mt-3 grid gap-3 border-t border-border pt-3 sm:grid-cols-2">
          <div className="text-sm">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{t("monitoring.clock")}</h3>
            {detail.isPending ? <p className="text-muted">{t("monitoring.loading")}</p> : null}
            {detail.isError ? <ProblemNotice error={detail.error} /> : null}
            {detail.data ? (
              <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                <dt className="text-muted">{t("monitoring.budget")}</dt>
                <dd>{detail.data.clock.budget_minutes} {t("monitoring.minutes")} ({detail.data.clock.basis})</dd>
                <dt className="text-muted">{t("monitoring.elapsed")}</dt>
                <dd>{detail.data.clock.active_minutes} / {t("monitoring.remaining")} {detail.data.clock.remaining_minutes}</dd>
                <dt className="text-muted">{t("monitoring.calendar")}</dt>
                <dd>{detail.data.clock.calendar_ref ?? "-"}</dd>
                <dt className="text-muted">{t("monitoring.pauses")}</dt>
                <dd>
                  {detail.data.clock.pauses.length === 0 ? "-" : detail.data.clock.pauses.map((p) => `${new Date(p.starts_at).toLocaleString()} → ${p.ends_at ? new Date(p.ends_at).toLocaleString() : t("monitoring.open")}`).join("; ")}
                  {detail.data.clock.due_estimate ? <span className="ml-2 text-warning">{detail.data.clock.due_estimate}</span> : null}
                </dd>
                <dt className="text-muted">{t("monitoring.thresholds")}</dt>
                <dd>{detail.data.thresholds.length === 0 ? "-" : detail.data.thresholds.map((x) => `${x.threshold_key} ${x.executed_at ? `(${x.disposition ?? "executed"})` : "(scheduled)"}`).join(", ")}</dd>
              </dl>
            ) : null}
          </div>
          <form className="flex flex-col gap-2 text-sm" onSubmit={(e) => e.preventDefault()}>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{t("monitoring.intervene")}</h3>
            <label htmlFor={ids.reason}>{t("policy.reason")}</label>
            <textarea id={ids.reason} className={FIELD} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} minLength={10} />
            <label htmlFor={ids.next}>{t("monitoring.nextAction")}</label>
            <input id={ids.next} className={FIELD} value={nextAction} onChange={(e) => setNextAction(e.target.value)} minLength={10} />
            <label htmlFor={ids.level}>{t("monitoring.level")}</label>
            <select id={ids.level} className={FIELD} value={level} onChange={(e) => setLevel(Number(e.target.value))}>
              {[1, 2, 3].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
            {escalate.isError ? <ProblemNotice error={escalate.error} /> : null}
            {acknowledge.isError ? <ProblemNotice error={acknowledge.error} /> : null}
            <button type="button" className={BUTTON} disabled={!valid || nextAction.trim().length < 10 || escalate.isPending} onClick={() => escalate.mutate()}>{t("monitoring.escalate")}</button>
            <p className="text-xs text-muted">{t("monitoring.escalateHelp")}</p>
          </form>
        </div>
      ) : null}
    </div>
  );
}
