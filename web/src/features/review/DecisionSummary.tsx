import { Link } from "react-router";

import type { CaseDetail } from "../../api/applications";
import { t } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";

/** Case-detail slice of UI-14/UI-17: the recorded decision (public reason for everyone, the
 *  rationale only where the server included it), issuance progress and the registry entry.
 *  Supervisors with a permitted approve/reject action get the link to the review page. */
export function DecisionSummary({ detail }: { detail: CaseDetail }) {
  const actions = new Map(detail.allowed_actions.map((a) => [a.key, a] as const));
  const canReview = actions.has("approve") || actions.has("reject");
  const { decision, issuance, certificate } = detail;
  if (!decision && !issuance && !certificate && !canReview) return null;
  return (
    <section className={CARD} aria-labelledby="case-decision">
      <h2 id="case-decision" className="text-base font-semibold">{t("decision.title")}</h2>
      {decision ? (
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
          <dt className="text-muted">{t("decision.kind")}</dt>
          <dd className="font-medium">{decision.kind} · #{decision.decision_number}</dd>
          <dt className="text-muted">{t("decision.recordedAt")}</dt>
          <dd>{new Date(decision.accepted_at).toLocaleString()}</dd>
          <dt className="text-muted">{t("decision.publicReason")}</dt>
          <dd>{decision.public_reason}</dd>
          {decision.reason ? (
            <>
              <dt className="text-muted">{t("review.reason")}</dt>
              <dd>{decision.reason}</dd>
            </>
          ) : null}
        </dl>
      ) : (
        <p className="mt-2 text-sm text-muted">{t("decision.none")}</p>
      )}
      {issuance && !certificate ? (
        <p role="status" className="mt-3 rounded-md bg-information-soft p-2 text-sm text-information">
          {t("decision.issuance")}: {issuance.certificate_number} · {issuance.state} · {t("decision.processing")}
        </p>
      ) : null}
      {certificate ? (
        <p className="mt-3 text-sm">
          {t("decision.certificate")}: <Link to={`/certificates/${certificate.certificate_id}`} className="text-primary">{certificate.certificate_number}</Link> · {certificate.effective_status}
          {certificate.is_demo ? <span className="ml-2 rounded-md bg-warning-soft px-2 py-0.5 text-xs text-warning">{t("certificates.demo")}</span> : null}
        </p>
      ) : null}
      {canReview ? (
        <Link to={`/applications/${detail.application_id}/review`} className="mt-4 inline-flex min-h-11 items-center rounded-md border border-primary px-4 font-medium text-primary hover:bg-primary-soft">
          {t("decision.openReview")}
        </Link>
      ) : null}
    </section>
  );
}
