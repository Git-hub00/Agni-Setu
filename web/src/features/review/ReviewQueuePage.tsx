import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { applicationsQuery } from "../../api/applications";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-4 shadow-[var(--shadow-card)]";

/** UI-14 `/reviews`: cases awaiting a decision, earliest due first, then receipt age. */
export function ReviewQueuePage() {
  const query = useQuery(applicationsQuery({ status: "REVIEW_PENDING" }));
  if (query.isPending) return <p className="text-sm text-muted">{t("review.loading")}</p>;
  if (query.isError) return <ProblemNotice error={query.error} />;
  const rows = [...query.data.items].sort((a, b) => {
    const dueA = a.next_due_at ? Date.parse(a.next_due_at) : Number.POSITIVE_INFINITY;
    const dueB = b.next_due_at ? Date.parse(b.next_due_at) : Number.POSITIVE_INFINITY;
    if (dueA !== dueB) return dueA - dueB;
    return Date.parse(a.submitted_at ?? a.created_at) - Date.parse(b.submitted_at ?? b.created_at);
  });
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold text-ink">{t("review.queueTitle")}</h1>
        <p className="text-sm text-muted">{t("review.queueHelp")}</p>
      </div>
      {rows.length === 0 ? <p className="text-sm text-muted">{t("review.queueEmpty")}</p> : null}
      <ul className="flex flex-col gap-2">
        {rows.map((a) => (
          <li key={a.application_id} className={`${CARD} flex flex-wrap items-center justify-between gap-3 text-sm`}>
            <div>
              <p className="font-medium">{a.public_reference ?? a.draft_reference} · {a.premises.display_name}</p>
              <p className="text-muted">
                {a.premises.category_key} · {a.owner_queue} · {t("review.due")} {a.next_due_at ? new Date(a.next_due_at).toLocaleString() : t("overview.noDue")}
              </p>
            </div>
            <Link to={`/applications/${a.application_id}/review`} className="inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white">
              {t("review.open")}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
