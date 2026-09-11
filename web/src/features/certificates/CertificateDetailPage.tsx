import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { certificateQuery, requestCertificateAccess } from "../../api/certificates";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";
const SECONDARY = "inline-flex min-h-11 items-center rounded-md border border-border bg-surface px-4 font-medium text-ink hover:bg-canvas disabled:opacity-60";

/** UI-17: status first, sample watermark label, provenance, ticketed download and the public
 *  verification link. Expired, suspended, revoked and superseded are shown as different states;
 *  an unavailable artifact leaves the registry state visible and never creates another one. */
export function CertificateDetailPage() {
  const { certificateId = "" } = useParams();
  const query = useQuery(certificateQuery(certificateId));
  const [copied, setCopied] = useState(false);
  const download = useMutation({
    mutationFn: () => requestCertificateAccess(certificateId),
    onSuccess: (ticket) => {
      window.open(ticket.url, "_blank", "noopener");
    },
  });
  if (query.isPending) return <p className="text-sm text-muted">{t("review.loading")}</p>;
  if (query.isError) return <ProblemNotice error={query.error} />;
  const { certificate } = query.data;
  const actions = new Map(certificate.allowed_actions.map((a) => [a.key, a] as const));
  const tone = certificate.effective_status === "ACTIVE" ? "bg-positive-soft text-positive" : certificate.effective_status === "REVOKED" ? "bg-danger-soft text-danger" : "bg-warning-soft text-warning";
  const copyLink = async () => {
    await navigator.clipboard.writeText(certificate.verification_url);
    setCopied(true);
  };
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
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button type="button" className={BUTTON} disabled={actions.get("download")?.enabled !== true || download.isPending} onClick={() => download.mutate()}>
            {download.isPending ? t("certificates.downloading") : t("certificates.download")}
          </button>
          <button type="button" className={SECONDARY} onClick={() => void copyLink()}>{t("certificates.copyLink")}</button>
          {copied ? <span role="status" className="text-sm text-positive">{t("certificates.copied")}</span> : null}
        </div>
        <p className="mt-3 text-xs text-muted">{t("certificates.actionsLater")}</p>
      </section>
      <section className={CARD} aria-labelledby="certificate-history">
        <h2 id="certificate-history" className="text-base font-semibold">{t("certificates.statusHistory")}</h2>
        {certificate.status_history.length === 0 ? <p className="mt-2 text-sm text-muted">{t("certificates.noHistory")}</p> : (
          <ul className="mt-2 list-disc pl-5 text-sm">
            {certificate.status_history.map((h) => <li key={`${h.action}-${h.effective_at}`}>{h.action} · {new Date(h.effective_at).toLocaleString()} · {h.public_reason}</li>)}
          </ul>
        )}
        <h3 className="mt-4 text-sm font-semibold">{t("certificates.obligations")}</h3>
        <p className="text-sm text-muted">{t("certificates.obligationsLater")}</p>
      </section>
    </div>
  );
}
