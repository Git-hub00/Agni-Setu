import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link, useParams } from "react-router";

import { applicationQuery, type CaseDetail } from "../../api/applications";
import { readinessQuery, recordDecision, type Blocker, type DecisionKind, type DecisionReadiness, type DecisionReceipt } from "../../api/decisions";
import { ApiError } from "../../api/errors";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 py-2 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";
const SECONDARY = "inline-flex min-h-11 items-center rounded-md border border-border bg-surface px-4 font-medium text-ink hover:bg-canvas disabled:opacity-60";

/** UI-14: evidence review with the server-calculated decision readiness. The decision panel
 *  never preselects an outcome, requires an explicit acknowledgment and a confirmation that
 *  summarises the evidence versions; approval shows "certificate processing", never "issued". */
export function ReviewPage() {
  const { applicationId = "" } = useParams();
  const queryClient = useQueryClient();
  const caseQuery = useQuery(applicationQuery(applicationId));
  const readiness = useQuery({ ...readinessQuery(applicationId), enabled: caseQuery.isSuccess });
  const [kind, setKind] = useState<DecisionKind | "">("");
  const [reason, setReason] = useState("");
  const [publicReason, setPublicReason] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [key] = useState(() => crypto.randomUUID()); // one stable command key per review attempt
  const [receipt, setReceipt] = useState<DecisionReceipt | null>(null);
  const ids = { reason: useId(), publicReason: useId(), ack: useId(), outcome: useId() };
  const decide = useMutation({
    mutationFn: async () => {
      if (!caseQuery.data || !readiness.data || kind === "") throw new Error("review incomplete");
      const evidence = readiness.data.readiness.evidence;
      if (!evidence.submission_revision_id) throw new Error("no accepted submission");
      return recordDecision(
        applicationId,
        {
          kind,
          submission_revision_id: evidence.submission_revision_id,
          ...(kind === "APPROVE" && evidence.report_id ? { report_id: evidence.report_id } : {}),
          reason,
          public_reason: publicReason,
          review_acknowledged: true,
        },
        caseQuery.data.etag,
        key,
      );
    },
    onSuccess: async (result) => {
      setReceipt(result);
      setConfirming(false);
      await queryClient.invalidateQueries({ queryKey: ["applications"] });
      await queryClient.invalidateQueries({ queryKey: ["decisions"] });
    },
    onError: async () => {
      // A conflict or changed evidence reloads the canonical state; the reviewer decides again.
      setConfirming(false);
      await queryClient.invalidateQueries({ queryKey: ["applications", "detail", applicationId] });
      await queryClient.invalidateQueries({ queryKey: ["decisions", "readiness", applicationId] });
    },
  });
  if (caseQuery.isPending) return <p className="text-sm text-muted">{t("review.loading")}</p>;
  if (caseQuery.isError) return <ProblemNotice error={caseQuery.error} />;
  const { detail } = caseQuery.data;
  if (receipt) return <ReceiptView receipt={receipt} applicationId={applicationId} />;
  const ready = readiness.data?.readiness ?? null;
  const canApprove = ready?.approve.eligible === true;
  const canReject = ready?.reject.eligible === true;
  const outcomeAllowed = (kind === "APPROVE" && canApprove) || (kind === "REJECT" && canReject);
  const formValid = outcomeAllowed && reason.trim().length >= 10 && publicReason.trim().length >= 10 && acknowledged;
  const conflict = decide.error instanceof ApiError && (decide.error.status === 409 || decide.error.status === 412);
  return (
    <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
      <div className="flex min-w-0 flex-1 flex-col gap-6">
        <div>
          <Link to="/reviews" className="text-sm text-primary">← {t("review.queueTitle")}</Link>
          <h1 className="mt-1 text-2xl font-semibold text-ink">{t("review.title")} · {detail.public_reference ?? detail.draft_reference}</h1>
          <p className="text-sm text-muted">{detail.premises.display_name} · {detail.premises.category_key} · {detail.status} · <Link to={`/applications/${applicationId}`} className="text-primary">{t("review.viewCase")}</Link></p>
        </div>
        <SubmissionSection detail={detail} />
        <ReportSection detail={detail} />
        <FindingsSection detail={detail} />
        <CorrespondenceSection detail={detail} applicationId={applicationId} />
      </div>
      <aside className="flex flex-col gap-4 lg:sticky lg:top-4 lg:w-[400px] lg:shrink-0" aria-labelledby="decision-readiness">
        <section className={CARD}>
          <h2 id="decision-readiness" className="text-base font-semibold">{t("review.readiness")}</h2>
          <p className="mt-1 text-xs text-muted">{t("review.readinessHelp")}</p>
          {readiness.isPending ? <p className="mt-3 text-sm text-muted">{t("review.loading")}</p> : null}
          {readiness.isError ? (
            readiness.error instanceof ApiError && readiness.error.status === 403 ? (
              <p role="status" className="mt-3 rounded-md bg-warning-soft p-2 text-sm text-warning">{t("review.noAccess")}</p>
            ) : (
              <div className="mt-3"><ProblemNotice error={readiness.error} /></div>
            )
          ) : null}
          {ready ? <ReadinessView ready={ready} /> : null}
        </section>
        {ready ? (
          <section className={CARD} aria-labelledby="decision-panel">
            <h2 id="decision-panel" className="text-base font-semibold">{t("review.outcome")}</h2>
            {conflict ? <p role="status" className="mt-2 rounded-md bg-warning-soft p-2 text-sm text-warning">{t("review.changed")}</p> : null}
            {decide.isError ? <div className="mt-2"><ProblemNotice error={decide.error} /></div> : null}
            {!confirming ? (
              <form className="mt-3 flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); if (formValid) setConfirming(true); }}>
                <fieldset>
                  <legend id={ids.outcome} className="text-sm font-medium">{t("review.outcome")}</legend>
                  <div className="mt-1 flex gap-4" role="radiogroup" aria-labelledby={ids.outcome}>
                    <label className="inline-flex min-h-11 items-center gap-2 text-sm">
                      <input type="radio" name="outcome" value="APPROVE" checked={kind === "APPROVE"} disabled={!canApprove} onChange={() => setKind("APPROVE")} />
                      {t("review.approve")}
                    </label>
                    <label className="inline-flex min-h-11 items-center gap-2 text-sm">
                      <input type="radio" name="outcome" value="REJECT" checked={kind === "REJECT"} disabled={!canReject} onChange={() => setKind("REJECT")} />
                      {t("review.reject")}
                    </label>
                  </div>
                </fieldset>
                <label htmlFor={ids.reason} className="text-sm font-medium">{t("review.reason")}</label>
                <textarea id={ids.reason} className={FIELD} rows={3} minLength={10} maxLength={4000} value={reason} onChange={(e) => setReason(e.target.value)} />
                <label htmlFor={ids.publicReason} className="text-sm font-medium">{t("review.publicReason")}</label>
                <textarea id={ids.publicReason} className={FIELD} rows={3} minLength={10} maxLength={4000} value={publicReason} onChange={(e) => setPublicReason(e.target.value)} />
                <label className="flex items-start gap-2 text-sm">
                  <input id={ids.ack} type="checkbox" className="mt-1" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} />
                  <span>{t("review.acknowledge")}</span>
                </label>
                <button type="submit" className={BUTTON} disabled={!formValid || decide.isPending}>{t("review.record")}</button>
              </form>
            ) : (
              <div className="mt-3 flex flex-col gap-3" role="group" aria-label={t("review.confirmTitle")}>
                <h3 className="text-sm font-semibold">{t("review.confirmTitle")}</h3>
                <p className="text-sm text-muted">{t("review.confirmBody")}</p>
                <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                  <dt className="text-muted">{t("review.outcome")}</dt>
                  <dd className="font-medium">{kind === "APPROVE" ? t("review.approve") : t("review.reject")}</dd>
                  <dt className="text-muted">{t("review.submissionRevision")}</dt>
                  <dd>#{ready.evidence.submission_number} · {ready.evidence.submission_sha256?.slice(0, 12)}</dd>
                  <dt className="text-muted">{t("review.reportRevision")}</dt>
                  <dd>{ready.evidence.report_revision ? `#${ready.evidence.report_revision} · ${ready.evidence.report_sha256?.slice(0, 12)}` : "-"}</dd>
                  <dt className="text-muted">{t("review.policyVersion")}</dt>
                  <dd>v{ready.evidence.policy_number}</dd>
                  <dt className="text-muted">{t("review.publicReason")}</dt>
                  <dd>{publicReason}</dd>
                </dl>
                <div className="flex flex-wrap gap-3">
                  <button type="button" className={BUTTON} disabled={decide.isPending} onClick={() => decide.mutate()}>{t("review.confirm")}</button>
                  <button type="button" className={SECONDARY} disabled={decide.isPending} onClick={() => setConfirming(false)}>{t("review.cancel")}</button>
                </div>
              </div>
            )}
          </section>
        ) : null}
      </aside>
    </div>
  );
}

function BlockerList({ blockers }: { blockers: Blocker[] }) {
  return (
    <ul className="mt-1 list-disc pl-5 text-sm">
      {blockers.map((b) => (
        <li key={b.code}>
          <span className="font-medium">{b.code}</span> · {b.message}
          {b.refs.length > 0 ? <span className="text-muted"> ({b.refs.join(", ")})</span> : null}
        </li>
      ))}
    </ul>
  );
}

function ReadinessView({ ready }: { ready: DecisionReadiness }) {
  return (
    <div className="mt-3 flex flex-col gap-3 text-sm">
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{t("review.authority")}</h3>
        <p>{ready.authority.grant_id ? `${ready.authority.scope ?? ""} · ${ready.authority.grant_id.slice(0, 8)}` : t("review.noAuthority")}</p>
      </div>
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{t("review.approve")}</h3>
        {ready.approve.eligible ? <p className="text-positive">{t("review.approveReady")}</p> : <><p className="text-warning">{t("review.blockedBy")}</p><BlockerList blockers={ready.approve.blockers} /></>}
      </div>
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{t("review.reject")}</h3>
        {ready.reject.eligible ? <p className="text-positive">{t("review.rejectReady")}</p> : <><p className="text-warning">{t("review.blockedBy")}</p><BlockerList blockers={ready.reject.blockers} /></>}
      </div>
      <p className="text-xs text-muted">{ready.notice}</p>
    </div>
  );
}

function SubmissionSection({ detail }: { detail: CaseDetail }) {
  const submission = detail.submission;
  return (
    <section className={CARD} aria-labelledby="review-submission">
      <h2 id="review-submission" className="text-base font-semibold">{t("review.submission")}</h2>
      {submission ? (
        <>
          <p className="mt-1 text-sm text-muted">#{submission.number} · {new Date(submission.accepted_at).toLocaleString()} · {t("review.policy")} v{submission.policy_number} · {submission.sha256.slice(0, 12)}</p>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
            {Object.entries(submission.fields).filter(([, value]) => value !== null && value !== undefined && value !== "").map(([field, value]) => (
              <div key={field} className="contents">
                <dt className="text-muted">{field}</dt>
                <dd>{String(value)}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-sm text-muted">{t("review.documents")}: {submission.documents.length}</p>
        </>
      ) : (
        <p className="mt-2 text-sm text-muted">{t("review.noSubmission")}</p>
      )}
    </section>
  );
}

function ReportSection({ detail }: { detail: CaseDetail }) {
  const withReports = detail.inspections.filter((i) => i.report);
  return (
    <section className={CARD} aria-labelledby="review-report">
      <h2 id="review-report" className="text-base font-semibold">{t("review.report")}</h2>
      {withReports.length === 0 ? <p className="mt-2 text-sm text-muted">{t("review.noReport")}</p> : null}
      <ul className="mt-3 flex flex-col gap-3">
        {withReports.map((i) => (
          <li key={i.inspection_id} className="rounded-md border border-border p-3 text-sm">
            <p className="font-medium">
              {t("review.attempt")} {i.attempt_number} · {i.purpose} · {t("review.accepted")} {i.report ? new Date(i.report.accepted_at).toLocaleString() : ""}
            </p>
            <p className={i.report?.eligible_for_review ? "text-positive" : "text-warning"}>
              {i.report?.eligible_for_review ? t("review.eligible") : t("review.notEligible")}
            </p>
            {i.report?.blockers && i.report.blockers.length > 0 ? (
              <ul className="mt-1 list-disc pl-5">
                {i.report.blockers.map((b) => <li key={`${b.code}-${b.item_code ?? ""}`}>{b.item_code ? `${b.item_code} · ` : ""}{b.message ?? b.code}</li>)}
              </ul>
            ) : null}
            <Link to={`/inspections/${i.inspection_id}`} className="mt-1 inline-block text-primary">{t("review.openInspection")}</Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function FindingsSection({ detail }: { detail: CaseDetail }) {
  const summary = detail.findings_summary;
  return (
    <section className={CARD} aria-labelledby="review-findings">
      <h2 id="review-findings" className="text-base font-semibold">{t("review.findings")}</h2>
      {summary ? (
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
          <dt className="text-muted">{t("review.openMandatory")}</dt><dd>{summary.open_mandatory}</dd>
          <dt className="text-muted">{t("review.openAdvisory")}</dt><dd>{summary.open_advisory}</dd>
          <dt className="text-muted">{t("review.verifiedClosed")}</dt><dd>{summary.verified_closed}</dd>
          <dt className="text-muted">{t("review.reinspection")}</dt><dd>{summary.reinspection_outstanding.length > 0 ? summary.reinspection_outstanding.join(", ") : "-"}</dd>
        </dl>
      ) : (
        <p className="mt-2 text-sm text-muted">-</p>
      )}
    </section>
  );
}

function CorrespondenceSection({ detail, applicationId }: { detail: CaseDetail; applicationId: string }) {
  return (
    <section className={CARD} aria-labelledby="review-correspondence">
      <h2 id="review-correspondence" className="text-base font-semibold">{t("review.correspondence")}</h2>
      {detail.notices.length === 0 ? <p className="mt-2 text-sm text-muted">{t("review.noCorrespondence")}</p> : null}
      <ul className="mt-3 flex flex-col gap-2 text-sm">
        {detail.notices.map((n) => (
          <li key={n.notice_id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-3">
            <span>{n.type} · round {n.round_number} · {n.state} · {n.open_items}/{n.items_total} open</span>
            <Link to={`/applications/${applicationId}/notices/${n.notice_id}`} className="text-primary">{t("review.openNotice")}</Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ReceiptView({ receipt, applicationId }: { receipt: DecisionReceipt; applicationId: string }) {
  const approved = receipt.kind === "APPROVE";
  return (
    <section className={CARD} aria-labelledby="decision-receipt">
      <h1 id="decision-receipt" className="text-2xl font-semibold text-ink">{approved ? t("review.approved") : t("review.rejected")}</h1>
      <p role="status" className={`mt-3 rounded-md p-3 text-sm ${approved ? "bg-information-soft text-information" : "bg-canvas text-ink"}`}>
        {approved ? t("review.processingNote") : receipt.public_reason}
      </p>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
        <dt className="text-muted">{t("applications.col.status")}</dt><dd>{receipt.status}</dd>
        {receipt.issuance ? (<><dt className="text-muted">{t("review.reservedNumber")}</dt><dd>{receipt.issuance.certificate_number} · {receipt.issuance.state}</dd></>) : null}
        <dt className="text-muted">{t("review.evidenceVersions")}</dt><dd>{receipt.evidence_sha256.slice(0, 16)}</dd>
      </dl>
      <div className="mt-4 flex flex-wrap gap-3">
        <Link to={`/applications/${applicationId}`} className={SECONDARY}>{t("review.viewCase")}</Link>
        <Link to="/certificates" className={SECONDARY}>{t("review.viewRegister")}</Link>
        <Link to="/reviews" className={SECONDARY}>{t("review.queueTitle")}</Link>
      </div>
    </section>
  );
}
