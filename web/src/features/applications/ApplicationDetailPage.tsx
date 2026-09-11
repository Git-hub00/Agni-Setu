import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { applicationQuery, requestDocumentAccess, type CaseDetail } from "../../api/applications";
import { resolveRouting, startScrutiny, timelineQuery } from "../../api/cases";
import { requireInspection } from "../../api/inspections";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";
import { NoticeActions, NoticesSection } from "../notices/CaseNotices";
import { DecisionSummary } from "../review/DecisionSummary";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";

/** UI-07: case header, summary, evidence with authorised access, audience-filtered timeline and
 *  the server's permitted actions (supervisor: start scrutiny, resolve routing). Every action
 *  refreshes the canonical case; a stale ETag surfaces as a conflict, never a silent overwrite. */
export function ApplicationDetailPage() {
  const { applicationId = "" } = useParams();
  const [params] = useSearchParams();
  const query = useQuery(applicationQuery(applicationId));
  const timeline = useQuery({ ...timelineQuery(applicationId), enabled: query.isSuccess });
  if (query.isPending) {
    return <p className="text-sm text-muted">{t("wizard.loading")}</p>;
  }
  if (query.isError) {
    return <ProblemNotice error={query.error} />;
  }
  const { detail, etag } = query.data;
  const actions = new Map(detail.allowed_actions.map((a) => [a.key, a] as const));
  const editable = actions.get("edit-draft")?.enabled === true;
  const receiptRef = params.get("receipt");
  const open = async (id: string) => {
    const url = await requestDocumentAccess(id, "PREVIEW");
    window.open(url, "_blank", "noopener");
  };
  const documents = detail.draft?.documents ?? [];
  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link to="/applications" className="text-sm text-primary">← {t("applications.title")}</Link>
        <h1 className="mt-1 text-2xl font-semibold text-ink">{detail.public_reference ?? detail.draft_reference}</h1>
        <p className="text-sm text-muted">{detail.premises.display_name} · {detail.premises.category_key} · {detail.status}</p>
      </div>
      {receiptRef && receiptRef === detail.public_reference ? (
        <div role="status" className="rounded-md border border-positive bg-positive-soft p-4 text-sm text-positive">
          <p className="font-medium">{t("receipt.title")} {detail.public_reference}</p>
          <p>{t("receipt.body")} {detail.submitted_at ? new Date(detail.submitted_at).toLocaleString() : ""} · {detail.owner_queue}</p>
        </div>
      ) : null}
      <section className={CARD} aria-labelledby="case-summary">
        <h2 id="case-summary" className="text-base font-semibold">{t("detail.summary")}</h2>
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-muted">{t("applications.col.status")}</dt>
          <dd>{detail.status}</dd>
          <dt className="text-muted">{t("applications.col.unit")}</dt>
          <dd>{detail.owner_queue}</dd>
          <dt className="text-muted">{t("detail.received")}</dt>
          <dd>{detail.submitted_at ? new Date(detail.submitted_at).toLocaleString() : t("detail.notReceived")}</dd>
          <dt className="text-muted">{t("applicability.policy")}</dt>
          <dd>{detail.submission ? `v${detail.submission.policy_number}` : detail.policy.policy_number ? `v${detail.policy.policy_number}` : "-"}</dd>
          {detail.obligations.length > 0 ? (
            <>
              <dt className="text-muted">{t("detail.dueBasis")}</dt>
              <dd>
                {detail.obligations.map((o) => (
                  <div key={o.obligation_id}>{o.kind} · {o.time_basis} · {o.due_at ? new Date(o.due_at).toLocaleString() : t("overview.noDue")} · {o.state}</div>
                ))}
              </dd>
            </>
          ) : null}
        </dl>
        {editable ? (
          <Link to={`/applications/${detail.application_id}/edit`} className={`${BUTTON} mt-4`}>
            {t("applications.continue")}
          </Link>
        ) : null}
      </section>
      {detail.routing_exception ? (
        <div role="alert" className="rounded-md border border-warning bg-warning-soft p-4 text-sm">
          <p className="font-medium text-warning">{t("detail.routingException")} {detail.routing_exception.code}</p>
          <p className="mt-1 text-ink">{t("detail.routingExceptionBody")} {detail.routing_exception.owner_queue}</p>
        </div>
      ) : null}
      <StaffActions detail={detail} etag={etag} />
      <DecisionSummary detail={detail} />
      <NoticesSection detail={detail} />
      <NoticeActions detail={detail} etag={etag} />
      {detail.inspections.length > 0 ? (
        <section className={CARD} aria-labelledby="case-inspections">
          <h2 id="case-inspections" className="text-base font-semibold">{t("detail.inspections")}</h2>
          <ul className="mt-3 flex flex-col gap-1 text-sm">
            {detail.inspections.map((i) => (
              <li key={i.inspection_id} className="flex flex-wrap items-center gap-3">
                <span>{t("queue.attempt")} {i.attempt_number} · {i.status}</span>
                <span className="text-muted">{i.scheduled_start ? `${new Date(i.scheduled_start).toLocaleString()} (${i.appointment_timezone})` : t("queue.notScheduled")}</span>
                {i.officer_name ? <span className="text-muted">{i.officer_name}</span> : null}
                {i.failed_reason_code ? <span className="text-warning">{i.failed_reason_code}</span> : null}
                {i.officer_name ? <Link to={`/inspections/${i.inspection_id}`} className="text-primary">{t("applications.view")}</Link> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <section className={CARD} aria-labelledby="case-documents">
        <h2 id="case-documents" className="text-base font-semibold">{t("detail.documents")}</h2>
        {detail.submission ? (
          <ul className="mt-3 flex flex-col gap-1 text-sm">
            {detail.submission.documents.map((d) => (
              <li key={d.document_version_id} className="flex flex-wrap items-center gap-3">
                <span>{d.requirement_code} · {d.document_version_id.slice(0, 8)}</span>
                <button type="button" className="text-primary" onClick={() => void open(d.document_version_id)}>{t("wizard.open")}</button>
              </li>
            ))}
          </ul>
        ) : documents.length > 0 ? (
          <ul className="mt-3 flex flex-col gap-1 text-sm">
            {documents.map((d) => (
              <li key={d.document_version_id} className="flex flex-wrap items-center gap-3">
                <span>{d.requirement_code} · {d.original_name} · {d.scan_state}</span>
                {d.scan_state === "CLEAN" ? (
                  <button type="button" className="text-primary" onClick={() => void open(d.document_version_id)}>{t("wizard.open")}</button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-muted">{t("detail.noDocuments")}</p>
        )}
      </section>
      <section className={CARD} aria-labelledby="case-timeline">
        <div className="flex items-center justify-between">
          <h2 id="case-timeline" className="text-base font-semibold">{t("detail.timeline")}</h2>
          {timeline.data ? <span className="text-xs text-muted">{t("overview.asOf")} {new Date(timeline.data.as_of).toLocaleTimeString()}</span> : null}
        </div>
        {timeline.isPending ? <p className="mt-2 text-sm text-muted">{t("detail.timelineLoading")}</p> : null}
        {timeline.isError ? <ProblemNotice error={timeline.error} /> : null}
        {timeline.data ? (
          <ol className="mt-3 flex flex-col gap-2 text-sm" data-testid="timeline">
            {timeline.data.items.map((e) => (
              <li key={e.event_id} className="flex flex-wrap gap-3 border-l-2 border-border pl-3">
                <span className="text-muted">{new Date(e.occurred_at).toLocaleString()}</span>
                <span className="font-medium">{e.event_type}</span>
                {e.audience === "INTERNAL" ? <span className="rounded-md bg-information-soft px-2 text-xs text-information">{t("detail.internal")}</span> : null}
              </li>
            ))}
          </ol>
        ) : null}
      </section>
      <section className={CARD} aria-labelledby="case-actions">
        <h2 id="case-actions" className="text-base font-semibold">{t("detail.actions")}</h2>
        <ul className="mt-3 text-sm">
          {detail.allowed_actions.map((a) => (
            <li key={a.key}>
              {a.key}: {a.enabled ? t("detail.actionAvailable") : `${t("detail.actionBlocked")} (${a.reason_code ?? "-"})`}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function StaffActions({ detail, etag }: { detail: CaseDetail; etag: string }) {
  const queryClient = useQueryClient();
  const actions = new Map(detail.allowed_actions.map((a) => [a.key, a] as const));
  const canStart = actions.get("start-scrutiny")?.enabled === true;
  const canResolve = actions.get("resolve-routing")?.enabled === true && detail.routing_exception !== null;
  const canRequire = actions.get("require-inspection")?.enabled === true;
  const [reason, setReason] = useState("");
  const [queueId, setQueueId] = useState("");
  const [jurisdictionId, setJurisdictionId] = useState("");
  const reasonId = useId();
  const queueField = useId();
  const jurisdictionField = useId();
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["applications"] });
    await queryClient.invalidateQueries({ queryKey: ["overview"] });
  };
  const start = useMutation({
    mutationFn: () => startScrutiny(detail.application_id, reason, etag, crypto.randomUUID()),
    onSuccess: refresh,
  });
  const require = useMutation({
    mutationFn: () => requireInspection(detail.application_id, reason, etag),
    onSuccess: async () => {
      await refresh();
      await queryClient.invalidateQueries({ queryKey: ["inspections"] });
    },
  });
  const resolve = useMutation({
    mutationFn: () =>
      resolveRouting(
        detail.application_id,
        {
          target_jurisdiction_id: jurisdictionId,
          target_queue_id: queueId,
          routing_artifact_id: detail.routing_exception?.routing_artifact_id ?? "",
          reason,
          exception_id: detail.routing_exception?.exception_id ?? "",
        },
        etag,
        crypto.randomUUID(),
      ),
    onSuccess: refresh,
  });
  if (!canStart && !canResolve && !canRequire) return null;
  return (
    <section className={CARD} aria-labelledby="staff-actions">
      <h2 id="staff-actions" className="text-base font-semibold">{t("detail.staffActions")}</h2>
      <div className="mt-3 flex flex-col gap-3">
        <div>
          <label htmlFor={reasonId} className="text-sm font-medium">{t("policy.reason")}</label>
          <textarea id={reasonId} className={FIELD} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} minLength={10} />
        </div>
        {canResolve ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor={jurisdictionField} className="text-sm font-medium">{t("detail.targetJurisdiction")}</label>
              <input id={jurisdictionField} className={FIELD} value={jurisdictionId} onChange={(e) => setJurisdictionId(e.target.value)} placeholder="UUID" />
            </div>
            <div>
              <label htmlFor={queueField} className="text-sm font-medium">{t("detail.targetQueue")}</label>
              <input id={queueField} className={FIELD} value={queueId} onChange={(e) => setQueueId(e.target.value)} placeholder="UUID" />
            </div>
          </div>
        ) : null}
        {start.isError ? <ProblemNotice error={start.error} /> : null}
        {resolve.isError ? <ProblemNotice error={resolve.error} /> : null}
        {require.isError ? <ProblemNotice error={require.error} /> : null}
        <div className="flex flex-wrap gap-3">
          {canRequire ? (
            <button type="button" className={BUTTON} disabled={require.isPending || reason.trim().length < 10} onClick={() => require.mutate()}>
              {t("detail.requireInspection")}
            </button>
          ) : null}
          {canResolve ? (
            <button type="button" className={BUTTON} disabled={resolve.isPending || reason.trim().length < 10 || !queueId || !jurisdictionId} onClick={() => resolve.mutate()}>
              {t("detail.resolveRouting")}
            </button>
          ) : null}
          {canStart ? (
            <button type="button" className={BUTTON} disabled={start.isPending || reason.trim().length < 10} onClick={() => start.mutate()}>
              {start.isPending ? t("submit.working") : t("detail.startScrutiny")}
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}
