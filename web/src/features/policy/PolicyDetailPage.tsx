import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";

import { policyDetailQuery, runPolicyCommand, type PolicyCommand, type PolicyDetail } from "../../api/policies";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t, type MessageKey } from "../../locales";
import { StateBadge } from "./PolicyListPage";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 text-sm text-ink";
const BUTTON =
  "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";

const COMMAND_LABEL: Record<PolicyCommand, MessageKey> = {
  "submit-review": "policy.action.submitReview",
  simulate: "policy.action.simulate",
  approve: "policy.action.approve",
  return: "policy.action.return",
  activate: "policy.action.activate",
};

/** UI-24 detail: governance facts and the actions the server currently allows. Every action
 *  posts the frozen candidate hash, a reason, the ETag precondition and an idempotency key;
 *  the server re-checks authority and separation of duties on each call (FR-27). */
export function PolicyDetailPage() {
  const { policyId = "" } = useParams();
  const detail = useQuery(policyDetailQuery(policyId));
  if (detail.isPending) {
    return <p className="text-sm text-muted">{t("policy.loading")}</p>;
  }
  if (detail.isError) {
    return <ProblemNotice error={detail.error} />;
  }
  const { policy, etag } = detail.data;
  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link to="/policy" className="text-sm text-primary">← {t("policy.title")}</Link>
        <h1 className="mt-1 flex items-center gap-3 text-2xl font-semibold text-ink">
          {policy.service_key} v{policy.number} <StateBadge state={policy.state} />
        </h1>
      </div>
      <section aria-labelledby="policy-facts" className={CARD}>
        <h2 id="policy-facts" className="text-base font-semibold text-ink">{t("policy.facts")}</h2>
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-muted">{t("policy.field.hash")}</dt>
          <dd className="font-mono text-xs break-all">{policy.payload_sha256}</dd>
          <dt className="text-muted">{t("policy.field.candidate")}</dt>
          <dd className="font-mono text-xs break-all">{policy.review_candidate_sha256 ?? "-"}</dd>
          <dt className="text-muted">{t("policy.field.effective")}</dt>
          <dd>
            {policy.effective_from ? new Date(policy.effective_from).toLocaleString() : "-"}
            {policy.effective_until ? ` → ${new Date(policy.effective_until).toLocaleString()}` : ""}
          </dd>
          <dt className="text-muted">{t("policy.field.approvalBasis")}</dt>
          <dd>{policy.approval_basis || "-"}</dd>
          <dt className="text-muted">{t("policy.field.returnedReason")}</dt>
          <dd>{policy.returned_reason || "-"}</dd>
        </dl>
        <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-muted">{t("policy.contributors")}</h3>
        <ul className="mt-1 text-sm">
          {policy.contributors.map((c) => (
            <li key={`${c.principal_id}:${c.at}`}>
              {c.action} · <span className="font-mono text-xs">{c.principal_id.slice(0, 8)}</span> · {new Date(c.at).toLocaleString()}
            </li>
          ))}
        </ul>
        <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-muted">{t("policy.simulations")}</h3>
        {policy.simulations.length === 0 ? <p className="mt-1 text-sm text-muted">{t("policy.noSimulations")}</p> : null}
        <ul className="mt-1 text-sm">
          {policy.simulations.map((s) => (
            <li key={s.simulation_id}>
              {s.passed ? t("policy.simulationPassed") : t("policy.simulationFailed")} · {s.suite} ·{" "}
              <span className="font-mono text-xs">{s.candidate_sha256.slice(0, 12)}</span> · {new Date(s.completed_at).toLocaleString()}
            </li>
          ))}
        </ul>
      </section>
      <ActionsPanel policy={policy} etag={etag ?? ""} />
      <section aria-labelledby="policy-payload" className={CARD}>
        <h2 id="policy-payload" className="text-base font-semibold text-ink">{t("policy.payload")}</h2>
        {/* Scrollable content must be reachable by keyboard (WCAG 2.1.1; axe scrollable-region-focusable):
            a focusable named region is the documented remedy, hence the tabIndex on a non-interactive element. */}
        <pre
          role="region"
          aria-label={t("policy.payloadJson")}
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- scrollable region must receive focus
          tabIndex={0}
          className="mt-3 max-h-96 overflow-auto rounded-md bg-canvas p-3 text-xs focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        >
          {JSON.stringify(policy.payload, null, 2)}
        </pre>
      </section>
    </div>
  );
}

function ActionsPanel({ policy, etag }: { policy: PolicyDetail; etag: string }) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [closePredecessor, setClosePredecessor] = useState(false);
  const reasonId = useId();
  const effectiveId = useId();
  const closeId = useId();
  const [lastCommand, setLastCommand] = useState<PolicyCommand | null>(null);

  const run = useMutation({
    mutationFn: (command: PolicyCommand) => {
      setLastCommand(command);
      const body: Record<string, unknown> = { reason };
      if (command === "simulate") {
        body.candidate_sha256 = policy.payload_sha256;
        body.fixture_suite_key = "demo-baseline-v1";
      }
      if (command === "approve") {
        body.candidate_sha256 = policy.payload_sha256;
        body.effective_from = effectiveFrom ? new Date(effectiveFrom).toISOString() : null;
        body.effective_until = null;
        if (closePredecessor) body.close_predecessor = true;
      }
      if (command === "activate") {
        body.approved_candidate_sha256 = policy.payload_sha256;
      }
      return runPolicyCommand({ policyId: policy.policy_version_id, command, etag, idempotencyKey: crypto.randomUUID(), body });
    },
    onSuccess: async () => {
      setReason("");
      await queryClient.invalidateQueries({ queryKey: ["policies"] });
    },
  });

  const enabled = new Map(policy.allowed_actions.map((a) => [a.key, a.enabled] as const));
  const commands: PolicyCommand[] = ["submit-review", "simulate", "approve", "return", "activate"];
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
  };

  return (
    <section aria-labelledby="policy-actions" className={CARD}>
      <h2 id="policy-actions" className="text-base font-semibold text-ink">{t("policy.actions")}</h2>
      <p className="mt-1 text-sm text-muted">{t("policy.actionsHelp")}</p>
      <form onSubmit={onSubmit} className="mt-4 flex flex-col gap-3">
        <div>
          <label htmlFor={reasonId} className="text-sm font-medium">{t("policy.reason")}</label>
          <textarea id={reasonId} className={FIELD} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} required minLength={10} />
        </div>
        {enabled.get("approve") ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor={effectiveId} className="text-sm font-medium">{t("policy.effectiveFrom")}</label>
              <input id={effectiveId} type="datetime-local" className={FIELD} value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
            </div>
            <div className="flex items-end gap-2 pb-2">
              <input id={closeId} type="checkbox" className="size-5" checked={closePredecessor} onChange={(e) => setClosePredecessor(e.target.checked)} />
              <label htmlFor={closeId} className="text-sm">{t("policy.closePredecessor")}</label>
            </div>
          </div>
        ) : null}
        {run.isError ? <ProblemNotice error={run.error} /> : null}
        {run.isSuccess && lastCommand ? (
          <p role="status" className="rounded-md bg-positive-soft p-3 text-sm text-positive">
            {t("policy.actionDone")} {t(COMMAND_LABEL[lastCommand])}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          {commands.map((command) => (
            <button
              key={command}
              type="button"
              className={BUTTON}
              disabled={!enabled.get(command) || run.isPending || reason.trim().length < 10}
              onClick={() => run.mutate(command)}
            >
              {t(COMMAND_LABEL[command])}
            </button>
          ))}
        </div>
      </form>
    </section>
  );
}
