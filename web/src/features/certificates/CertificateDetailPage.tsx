import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { applicationQuery } from "../../api/applications";
import { certificateQuery, createRenewal, recordStatusAction, requestCertificateAccess, type CertificateDetail, type StatusAction } from "../../api/certificates";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t, type MessageKey } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 py-2 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";
const SECONDARY = "inline-flex min-h-11 items-center rounded-md border border-border bg-surface px-4 font-medium text-ink hover:bg-canvas disabled:opacity-60";
const ACTION_LABEL: Record<StatusAction, MessageKey> = {
  SUSPEND: "certificates.action.SUSPEND",
  REINSTATE: "certificates.action.REINSTATE",
  REVOKE: "certificates.action.REVOKE",
  SUPERSEDE: "certificates.action.SUPERSEDE",
};

/** UI-17: status first, sample watermark label, provenance, ticketed download, the public
 *  verification link, the holder's renewal and the authority's status dialog. Only the
 *  transitions the server lists are offered; expired records are never reinstated. */
export function CertificateDetailPage() {
  const { certificateId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const query = useQuery(certificateQuery(certificateId));
  const [copied, setCopied] = useState(false);
  const download = useMutation({
    mutationFn: () => requestCertificateAccess(certificateId),
    onSuccess: (ticket) => {
      window.open(ticket.url, "_blank", "noopener");
    },
  });
  const renewal = useMutation({
    mutationFn: () => createRenewal(certificateId),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["certificates"] });
      await queryClient.invalidateQueries({ queryKey: ["applications"] });
      await navigate(`/applications/${result.data.application_id}/edit`);
    },
  });
  if (query.isPending) return <p className="text-sm text-muted">{t("review.loading")}</p>;
  if (query.isError) return <ProblemNotice error={query.error} />;
  const { certificate, etag } = query.data;
  const actions = new Map(certificate.allowed_actions.map((a) => [a.key, a] as const));
  const tone = certificate.effective_status === "ACTIVE" ? "bg-positive-soft text-positive" : certificate.effective_status === "REVOKED" ? "bg-danger-soft text-danger" : "bg-warning-soft text-warning";
  const copyLink = async () => {
    await navigator.clipboard.writeText(certificate.verification_url);
    setCopied(true);
  };
  const statusActions = certificate.allowed_status_actions.filter((a) => a.enabled);
  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link to="/certificates" className="text-sm text-primary">← {t("certificates.back")}</Link>
        <h1 className="mt-1 text-2xl font-semibold text-ink">{t("certificates.detailTitle")} {certificate.certificate_number}</h1>
        <p className="mt-1 flex flex-wrap items-center gap-2 text-sm">
          <span role="status" className={`rounded-md px-2 py-0.5 font-medium ${tone}`}>{certificate.effective_status}</span>
          {certificate.demo_notice ? <span className="rounded-md bg-warning-soft px-2 py-0.5 font-medium text-warning">{certificate.demo_notice}</span> : null}
        </p>
      </div>
      <section className={CARD} aria-labelledby="certificate-facts">
        <h2 id="certificate-facts" className="text-base font-semibold">{t("detail.summary")}</h2>
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-muted">{t("certificates.number")}</dt><dd>{certificate.certificate_number}</dd>
          <dt className="text-muted">{t("certificates.premises")}</dt><dd>{certificate.premises.display_name} · {certificate.premises.locality} · {certificate.premises.category_key}</dd>
          <dt className="text-muted">{t("certificates.issued")}</dt><dd>{new Date(certificate.issued_at).toLocaleString()}</dd>
          <dt className="text-muted">{t("certificates.validUntil")}</dt><dd>{certificate.valid_until ? new Date(certificate.valid_until).toLocaleString() : "-"}</dd>
          <dt className="text-muted">{t("certificates.issuer")}</dt><dd>{certificate.issuer_reference}</dd>
          <dt className="text-muted">{t("certificates.recorded")}</dt><dd>{certificate.recorded_status} · {certificate.outcome_kind}</dd>
          <dt className="text-muted">{t("certificates.related")}</dt>
          <dd><Link to={`/applications/${certificate.application_id}`} className="text-primary">{certificate.public_reference ?? certificate.application_id}</Link></dd>
          {certificate.predecessor_id ? (<><dt className="text-muted">{t("certificates.predecessor")}</dt><dd><Link to={`/certificates/${certificate.predecessor_id}`} className="text-primary">{certificate.predecessor_id.slice(0, 8)}</Link></dd></>) : null}
          {certificate.successor_ids.length > 0 ? (<><dt className="text-muted">{t("certificates.successor")}</dt><dd>{certificate.successor_ids.map((id) => <Link key={id} to={`/certificates/${id}`} className="mr-2 text-primary">{id.slice(0, 8)}</Link>)}</dd></>) : null}
        </dl>
      </section>
      <section className={CARD} aria-labelledby="certificate-artifact">
        <h2 id="certificate-artifact" className="text-base font-semibold">{t("certificates.artifact")}</h2>
        {certificate.artifact ? (
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
            <dt className="text-muted">{t("certificates.mode")}</dt><dd>{certificate.artifact.mode} · {certificate.artifact.renderer}</dd>
            <dt className="text-muted">SHA-256</dt><dd className="break-all">{certificate.artifact.sha256}</dd>
            <dt className="text-muted">{t("certificates.verificationLink")}</dt><dd className="break-all">{certificate.verification_url}</dd>
          </dl>
        ) : (
          <p role="status" className="mt-2 rounded-md bg-warning-soft p-2 text-sm text-warning">{t("certificates.artifactUnavailable")}</p>
        )}
        {download.isError ? <div className="mt-3"><ProblemNotice error={download.error} /></div> : null}
        {renewal.isError ? <div className="mt-3"><ProblemNotice error={renewal.error} /></div> : null}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button type="button" className={BUTTON} disabled={actions.get("download")?.enabled !== true || download.isPending} onClick={() => download.mutate()}>
            {download.isPending ? t("certificates.downloading") : t("certificates.download")}
          </button>
          <button type="button" className={SECONDARY} onClick={() => void copyLink()}>{t("certificates.copyLink")}</button>
          {actions.get("renewal")?.enabled ? (
            <button type="button" className={SECONDARY} disabled={renewal.isPending} onClick={() => renewal.mutate()}>{t("certificates.renew")}</button>
          ) : null}
          {copied ? <span role="status" className="text-sm text-positive">{t("certificates.copied")}</span> : null}
        </div>
        <p className="mt-3 text-xs text-muted">{t("certificates.renewHint")}</p>
      </section>
      <section className={CARD} aria-labelledby="certificate-history">
        <h2 id="certificate-history" className="text-base font-semibold">{t("certificates.statusHistory")}</h2>
        {certificate.status_history.length === 0 ? <p className="mt-2 text-sm text-muted">{t("certificates.noHistory")}</p> : (
          <ol className="mt-2 flex flex-col gap-2 text-sm">
            {certificate.status_history.map((h) => (
              <li key={h.instrument_id} className="rounded-md border border-border p-3">
                <p className="font-medium">{t(ACTION_LABEL[h.action])} · {h.status_before} → {h.status_after} · {new Date(h.effective_at).toLocaleString()}</p>
                <p className="text-muted">{h.public_reason}</p>
                {h.reason ? <p className="mt-1 text-xs text-muted">{t("review.reason")}: {h.reason}</p> : null}
              </li>
            ))}
          </ol>
        )}
        <h3 className="mt-4 text-sm font-semibold">{t("certificates.renewals")}</h3>
        {certificate.renewals.length === 0 ? <p className="text-sm text-muted">{t("certificates.noRenewals")}</p> : (
          <ul className="mt-1 flex flex-col gap-1 text-sm">
            {certificate.renewals.map((r) => (
              <li key={r.application_id}><Link to={`/applications/${r.application_id}`} className="text-primary">{r.public_reference ?? r.draft_reference}</Link> · {r.status}</li>
            ))}
          </ul>
        )}
        <h3 className="mt-4 text-sm font-semibold">{t("certificates.obligations")}</h3>
        <p className="text-sm text-muted">{t("certificates.obligationsLater")}</p>
      </section>
      {statusActions.length > 0 ? <StatusActionForm certificate={certificate} etag={etag} /> : null}
    </div>
  );
}

function StatusActionForm({ certificate, etag }: { certificate: CertificateDetail; etag: string }) {
  const queryClient = useQueryClient();
  const caseQuery = useQuery(applicationQuery(certificate.application_id));
  const enabled = certificate.allowed_status_actions.filter((a) => a.enabled).map((a) => a.action);
  const [action, setAction] = useState<StatusAction>(enabled[0] ?? "SUSPEND");
  const [reason, setReason] = useState("");
  const [publicReason, setPublicReason] = useState("");
  const [evidence, setEvidence] = useState("");
  const [successor, setSuccessor] = useState("");
  const ids = { action: useId(), reason: useId(), publicReason: useId(), evidence: useId(), successor: useId() };
  const needsEvidence = action === "SUSPEND" || action === "REVOKE";
  const mutation = useMutation({
    mutationFn: () =>
      recordStatusAction(
        certificate.certificate_id,
        {
          action,
          reason: reason.trim(),
          public_reason: publicReason.trim(),
          ...(evidence ? { evidence_document_id: evidence } : {}),
          ...(action === "SUPERSEDE" && successor.trim() ? { successor_certificate_id: successor.trim() } : {}),
        },
        etag,
      ),
    onSuccess: async () => {
      setReason("");
      setPublicReason("");
      await queryClient.invalidateQueries({ queryKey: ["certificates"] });
      await queryClient.invalidateQueries({ queryKey: ["applications"] });
    },
  });
  const documents = caseQuery.data?.detail.submission?.documents ?? [];
  const valid = reason.trim().length >= 10 && publicReason.trim().length >= 10 && (!needsEvidence || evidence !== "") && (action !== "SUPERSEDE" || successor.trim().length > 0);
  return (
    <section className={CARD} aria-labelledby="certificate-status-action">
      <h2 id="certificate-status-action" className="text-base font-semibold">{t("certificates.statusActionTitle")}</h2>
      <p className="mt-1 text-xs text-muted">{t("certificates.statusActionHelp")}</p>
      <form className="mt-3 flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); if (valid) mutation.mutate(); }}>
        <div>
          <label htmlFor={ids.action} className="text-sm font-medium">{t("certificates.actionLabel")}</label>
          <select id={ids.action} className={FIELD} value={action} onChange={(e) => setAction(e.target.value as StatusAction)}>
            {enabled.map((a) => <option key={a} value={a}>{t(ACTION_LABEL[a])}</option>)}
          </select>
        </div>
        <label htmlFor={ids.reason} className="text-sm font-medium">{t("review.reason")}</label>
        <textarea id={ids.reason} className={FIELD} rows={2} minLength={10} value={reason} onChange={(e) => setReason(e.target.value)} />
        <label htmlFor={ids.publicReason} className="text-sm font-medium">{t("review.publicReason")}</label>
        <textarea id={ids.publicReason} className={FIELD} rows={2} minLength={10} value={publicReason} onChange={(e) => setPublicReason(e.target.value)} />
        <div>
          <label htmlFor={ids.evidence} className="text-sm font-medium">{t("certificates.evidence")}{needsEvidence ? " *" : ""}</label>
          <select id={ids.evidence} className={FIELD} value={evidence} onChange={(e) => setEvidence(e.target.value)}>
            <option value="">{t("certificates.evidenceNone")}</option>
            {documents.map((d) => <option key={d.document_version_id} value={d.document_version_id}>{d.requirement_code} · {d.document_version_id.slice(0, 8)}</option>)}
          </select>
        </div>
        {action === "SUPERSEDE" ? (
          <div>
            <label htmlFor={ids.successor} className="text-sm font-medium">{t("certificates.successorId")}</label>
            <input id={ids.successor} className={FIELD} value={successor} onChange={(e) => setSuccessor(e.target.value)} placeholder="UUID" />
          </div>
        ) : null}
        {mutation.isError ? <ProblemNotice error={mutation.error} /> : null}
        {mutation.isSuccess ? <p role="status" className="rounded-md bg-positive-soft p-2 text-sm text-positive">{t("certificates.statusRecorded")}</p> : null}
        <button type="submit" className={BUTTON} disabled={!valid || mutation.isPending}>{t("certificates.recordStatus")}</button>
      </form>
    </section>
  );
}
