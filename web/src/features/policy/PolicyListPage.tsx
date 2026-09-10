import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { policiesQuery, type PolicyState } from "../../api/policies";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";

const STATE_TONE: Record<PolicyState, string> = {
  DRAFT: "bg-canvas text-ink",
  IN_REVIEW: "bg-information-soft text-information",
  RETURNED: "bg-warning-soft text-warning",
  APPROVED: "bg-positive-soft text-positive",
  SCHEDULED: "bg-positive-soft text-positive",
  ACTIVE: "bg-positive text-white",
  RETIRED: "bg-canvas text-muted",
};

export function StateBadge({ state }: { state: PolicyState }) {
  return <span className={`inline-block rounded-md px-2 py-0.5 text-xs font-medium ${STATE_TONE[state]}`}>{state}</span>;
}

/** UI-24 list: every version of every lineage with its governance state. Read access is decided
 *  by the server (admin, supervisor, approver, leadership or an approval/activation grant). */
export function PolicyListPage() {
  const policies = useQuery(policiesQuery);
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold text-ink">{t("policy.title")}</h1>
      <p className="text-sm text-muted">{t("policy.intro")}</p>
      {policies.isPending ? <p className="text-sm text-muted">{t("policy.loading")}</p> : null}
      {policies.isError ? <ProblemNotice error={policies.error} /> : null}
      {policies.data && policies.data.length === 0 ? <p className="text-sm text-muted">{t("policy.empty")}</p> : null}
      {policies.data && policies.data.length > 0 ? (
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-muted">
              <th scope="col" className="py-2">{t("policy.field.service")}</th>
              <th scope="col" className="py-2">{t("policy.field.number")}</th>
              <th scope="col" className="py-2">{t("policy.field.state")}</th>
              <th scope="col" className="py-2">{t("policy.field.effective")}</th>
              <th scope="col" className="py-2">{t("policy.field.hash")}</th>
            </tr>
          </thead>
          <tbody>
            {policies.data.map((p) => (
              <tr key={p.policy_version_id} className="border-t border-border">
                <td className="py-2">
                  <Link to={`/policy/${p.policy_version_id}`} className="font-medium text-primary">
                    {p.service_key}
                  </Link>
                </td>
                <td className="py-2">v{p.number}</td>
                <td className="py-2"><StateBadge state={p.state} /></td>
                <td className="py-2">
                  {p.effective_from ? new Date(p.effective_from).toLocaleString() : "-"}
                  {p.effective_until ? ` → ${new Date(p.effective_until).toLocaleString()}` : ""}
                </td>
                <td className="py-2 font-mono text-xs">{p.payload_sha256.slice(0, 12)}…</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}
