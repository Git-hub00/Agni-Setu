import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";

import { applicationQuery, requestDocumentAccess } from "../../api/applications";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";

/** UI-07 (B05 slice): case header, summary, documents with authorised access and the server's
 *  allowed actions with their safe blockers. Timeline, notices and outcome tabs arrive with B06+. */
export function ApplicationDetailPage() {
  const { applicationId = "" } = useParams();
  const query = useQuery(applicationQuery(applicationId));
  if (query.isPending) {
    return <p className="text-sm text-muted">{t("wizard.loading")}</p>;
  }
  if (query.isError) {
    return <ProblemNotice error={query.error} />;
  }
  const { detail } = query.data;
  const editable = detail.allowed_actions.find((a) => a.key === "edit-draft")?.enabled === true;
  const open = async (id: string) => {
    const url = await requestDocumentAccess(id, "PREVIEW");
    window.open(url, "_blank", "noopener");
  };
  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link to="/applications" className="text-sm text-primary">← {t("applications.title")}</Link>
        <h1 className="mt-1 text-2xl font-semibold text-ink">{detail.public_reference ?? detail.draft_reference}</h1>
        <p className="text-sm text-muted">{detail.premises.display_name} · {detail.premises.category_key} · {detail.status}</p>
      </div>
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
          <dd>{detail.policy.policy_number ? `v${detail.policy.policy_number}` : "-"}</dd>
        </dl>
        {editable ? (
          <Link to={`/applications/${detail.application_id}/edit`} className="mt-4 inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white">
            {t("applications.continue")}
          </Link>
        ) : null}
      </section>
      <section className={CARD} aria-labelledby="case-documents">
        <h2 id="case-documents" className="text-base font-semibold">{t("detail.documents")}</h2>
        {detail.draft && detail.draft.documents.length > 0 ? (
          <ul className="mt-3 flex flex-col gap-1 text-sm">
            {detail.draft.documents.map((d) => (
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
