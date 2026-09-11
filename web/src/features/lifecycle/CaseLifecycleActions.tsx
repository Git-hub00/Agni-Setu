import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import type { CaseDetail } from "../../api/applications";
import { createHold, releaseHold, returnForClarification, withdrawApplication } from "../../api/lifecycle";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 py-2 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";
const DANGER = "inline-flex min-h-11 items-center rounded-md bg-danger px-4 font-medium text-white disabled:opacity-60";
const SECONDARY = "inline-flex min-h-11 items-center rounded-md border border-border bg-surface px-4 font-medium text-ink hover:bg-canvas disabled:opacity-60";

/** UI-07 lifecycle controls (B13): the applicant's guarded withdrawal with a reasoned
 *  confirmation, the supervisor's hold controls listing the affected obligations, and the
 *  return-for-clarification route. Buttons follow the server's allowed_actions and every guard
 *  is rechecked server-side. */
export function CaseLifecycleActions({ detail, etag }: { detail: CaseDetail; etag: string }) {
  const actions = new Map(detail.allowed_actions.map((a) => [a.key, a] as const));
  const canWithdraw = actions.get("withdraw")?.enabled === true;
  const canHold = actions.get("add-hold")?.enabled === true;
  const canRelease = actions.get("release-hold")?.enabled === true;
  const canReturn = actions.get("return-for-clarification")?.enabled === true;
  if (!canWithdraw && !canHold && !canRelease && !canReturn && !detail.on_hold) return null;
  return (
    <section className={CARD} aria-labelledby="case-lifecycle">
      <h2 id="case-lifecycle" className="text-base font-semibold">{t("lifecycle.title")}</h2>
      {detail.on_hold ? (
        <p role="status" className="mt-2 rounded-md border border-warning bg-warning-soft p-3 text-sm text-ink">
          <span className="font-medium text-warning">{t("lifecycle.onHold")}</span> {t("lifecycle.onHoldBody")}
        </p>
      ) : null}
      <div className="mt-4 flex flex-col gap-6">
        {canWithdraw ? <WithdrawBlock detail={detail} etag={etag} /> : null}
        {canHold ? <HoldBlock detail={detail} etag={etag} /> : null}
        {detail.holds && detail.holds.length > 0 ? <ReleaseBlock detail={detail} canRelease={canRelease} /> : null}
        {canReturn ? <ReturnBlock detail={detail} etag={etag} /> : null}
      </div>
    </section>
  );
}

function useRefresh(applicationId: string) {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ["applications"] });
    await queryClient.invalidateQueries({ queryKey: ["cases", "timeline", applicationId] });
    await queryClient.invalidateQueries({ queryKey: ["overview"] });
    await queryClient.invalidateQueries({ queryKey: ["inspections"] });
  };
}

function WithdrawBlock({ detail, etag }: { detail: CaseDetail; etag: string }) {
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const id = useId();
  const refresh = useRefresh(detail.application_id);
  const withdraw = useMutation({
    mutationFn: () => withdrawApplication(detail.application_id, reason, etag),
    onSuccess: async () => {
      setConfirming(false);
      await refresh();
    },
  });
  return (
    <div>
      <h3 className="text-sm font-semibold">{t("lifecycle.withdraw")}</h3>
      <p className="text-xs text-muted">{t("lifecycle.withdrawHelp")}</p>
      <label htmlFor={id} className="mt-2 block text-sm font-medium">{t("lifecycle.reason")}</label>
      <textarea id={id} className={FIELD} rows={2} minLength={10} maxLength={4000} value={reason} onChange={(e) => setReason(e.target.value)} />
      {withdraw.isError ? <div className="mt-2"><ProblemNotice error={withdraw.error} /></div> : null}
      {!confirming ? (
        <button type="button" className={`${DANGER} mt-3`} disabled={reason.trim().length < 10} onClick={() => setConfirming(true)}>
          {t("lifecycle.withdraw")}
        </button>
      ) : (
        <div role="group" aria-label={t("lifecycle.withdrawConfirmTitle")} className="mt-3 rounded-md border border-danger bg-danger-soft p-3 text-sm">
          <p className="font-medium text-danger">{t("lifecycle.withdrawConfirmTitle")}</p>
          <p className="mt-1 text-ink">{t("lifecycle.withdrawConfirmBody")} {detail.public_reference ?? detail.draft_reference}</p>
          <div className="mt-3 flex flex-wrap gap-3">
            <button type="button" className={DANGER} disabled={withdraw.isPending} onClick={() => withdraw.mutate()}>{t("lifecycle.withdrawConfirm")}</button>
            <button type="button" className={SECONDARY} disabled={withdraw.isPending} onClick={() => setConfirming(false)}>{t("review.cancel")}</button>
          </div>
        </div>
      )}
    </div>
  );
}

function HoldBlock({ detail, etag }: { detail: CaseDetail; etag: string }) {
  const [kind, setKind] = useState<"ADMINISTRATIVE" | "COURT_ORDER">("ADMINISTRATIVE");
  const [reason, setReason] = useState("");
  const [basis, setBasis] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [blockTransitions, setBlockTransitions] = useState(true);
  const [blockDecisions, setBlockDecisions] = useState(false);
  const ids = { kind: useId(), reason: useId(), basis: useId() };
  const refresh = useRefresh(detail.application_id);
  const active = detail.obligations.filter((o) => o.state === "ACTIVE");
  const hold = useMutation({
    mutationFn: () =>
      createHold(
        detail.application_id,
        {
          kind,
          reason,
          affected_obligation_ids: selected,
          command_block_scope: [...(blockTransitions ? ["TRANSITIONS"] : []), ...(blockDecisions ? ["DECISIONS"] : [])],
          ...(basis.trim() ? { basis_document_id: basis.trim() } : {}),
        },
        etag,
      ),
    onSuccess: refresh,
  });
  const documents = detail.submission?.documents ?? [];
  return (
    <div>
      <h3 className="text-sm font-semibold">{t("lifecycle.hold")}</h3>
      <p className="text-xs text-muted">{t("lifecycle.holdHelp")}</p>
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor={ids.kind} className="text-sm font-medium">{t("lifecycle.holdKind")}</label>
          <select id={ids.kind} className={FIELD} value={kind} onChange={(e) => setKind(e.target.value as "ADMINISTRATIVE" | "COURT_ORDER")}>
            <option value="ADMINISTRATIVE">{t("lifecycle.kind.ADMINISTRATIVE")}</option>
            <option value="COURT_ORDER">{t("lifecycle.kind.COURT_ORDER")}</option>
          </select>
        </div>
        <div>
          <label htmlFor={ids.basis} className="text-sm font-medium">{t("lifecycle.holdBasis")}</label>
          <select id={ids.basis} className={FIELD} value={basis} onChange={(e) => setBasis(e.target.value)}>
            <option value="">{t("lifecycle.holdBasisNone")}</option>
            {documents.map((d) => (
              <option key={d.document_version_id} value={d.document_version_id}>{d.requirement_code} · {d.document_version_id.slice(0, 8)}</option>
            ))}
          </select>
        </div>
      </div>
      <label htmlFor={ids.reason} className="mt-2 block text-sm font-medium">{t("lifecycle.reason")}</label>
      <textarea id={ids.reason} className={FIELD} rows={2} minLength={10} value={reason} onChange={(e) => setReason(e.target.value)} />
      <fieldset className="mt-2">
        <legend className="text-sm font-medium">{t("lifecycle.holdObligations")}</legend>
        {active.length === 0 ? <p className="text-xs text-muted">{t("lifecycle.holdNoObligations")}</p> : null}
        {active.map((o) => (
          <label key={o.obligation_id} className="flex min-h-11 items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={selected.includes(o.obligation_id)}
              onChange={(e) => setSelected((prev) => (e.target.checked ? [...prev, o.obligation_id] : prev.filter((x) => x !== o.obligation_id)))}
            />
            {o.kind} · {o.time_basis} · {o.due_at ? new Date(o.due_at).toLocaleString() : t("overview.noDue")}
          </label>
        ))}
      </fieldset>
      <fieldset className="mt-2">
        <legend className="text-sm font-medium">{t("lifecycle.holdScope")}</legend>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input type="checkbox" checked={blockTransitions} onChange={(e) => setBlockTransitions(e.target.checked)} /> {t("lifecycle.scope.TRANSITIONS")}
        </label>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input type="checkbox" checked={blockDecisions} onChange={(e) => setBlockDecisions(e.target.checked)} /> {t("lifecycle.scope.DECISIONS")}
        </label>
      </fieldset>
      {hold.isError ? <div className="mt-2"><ProblemNotice error={hold.error} /></div> : null}
      <button type="button" className={`${BUTTON} mt-3`} disabled={hold.isPending || reason.trim().length < 10} onClick={() => hold.mutate()}>
        {t("lifecycle.holdCreate")}
      </button>
    </div>
  );
}

function ReleaseBlock({ detail, canRelease }: { detail: CaseDetail; canRelease: boolean }) {
  const [reason, setReason] = useState("");
  const id = useId();
  const refresh = useRefresh(detail.application_id);
  const release = useMutation({
    mutationFn: (hold: { hold_id: string; etag: string }) => releaseHold(hold.hold_id, reason, hold.etag),
    onSuccess: refresh,
  });
  return (
    <div>
      <h3 className="text-sm font-semibold">{t("lifecycle.activeHolds")}</h3>
      <ul className="mt-2 flex flex-col gap-2 text-sm">
        {(detail.holds ?? []).map((h) => (
          <li key={h.hold_id} className="rounded-md border border-border p-3">
            <p className="font-medium">{t(`lifecycle.kind.${h.kind}`)} · {new Date(h.starts_at).toLocaleString()}</p>
            <p className="text-muted">{h.reason}</p>
            <p className="text-xs text-muted">
              {t("lifecycle.holdObligations")}: {h.affected_obligation_ids.length} · {t("lifecycle.holdScope")}: {h.command_block_scope.join(", ") || t("lifecycle.scopeNone")}
            </p>
            {canRelease ? (
              <div className="mt-2 flex flex-wrap items-end gap-3">
                <div className="flex-1">
                  <label htmlFor={`${id}-${h.hold_id}`} className="text-sm font-medium">{t("lifecycle.reason")}</label>
                  <textarea id={`${id}-${h.hold_id}`} className={FIELD} rows={1} value={reason} onChange={(e) => setReason(e.target.value)} />
                </div>
                <button type="button" className={SECONDARY} disabled={release.isPending || reason.trim().length < 10} onClick={() => release.mutate({ hold_id: h.hold_id, etag: h.etag })}>
                  {t("lifecycle.holdRelease")}
                </button>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
      {release.isError ? <div className="mt-2"><ProblemNotice error={release.error} /></div> : null}
    </div>
  );
}

function ReturnBlock({ detail, etag }: { detail: CaseDetail; etag: string }) {
  const reports = detail.inspections.filter((i) => i.report?.report_id);
  const latest = reports.length > 0 ? reports[reports.length - 1] : null;
  const [code, setCode] = useState("");
  const [text, setText] = useState("");
  const [reason, setReason] = useState("");
  const ids = { code: useId(), text: useId(), reason: useId() };
  const refresh = useRefresh(detail.application_id);
  const back = useMutation({
    mutationFn: () =>
      returnForClarification(
        detail.application_id,
        { report_id: latest?.report?.report_id ?? "", items_requiring_clarification: [{ code: code.trim().toUpperCase(), text: text.trim() }], reason },
        etag,
      ),
    onSuccess: refresh,
  });
  if (!latest?.report?.report_id) return null;
  return (
    <div>
      <h3 className="text-sm font-semibold">{t("lifecycle.return")}</h3>
      <p className="text-xs text-muted">{t("lifecycle.returnHelp")}</p>
      <div className="mt-2 grid gap-3 sm:grid-cols-[120px_1fr]">
        <div>
          <label htmlFor={ids.code} className="text-sm font-medium">{t("lifecycle.itemCode")}</label>
          <input id={ids.code} className={FIELD} value={code} onChange={(e) => setCode(e.target.value)} placeholder="C02" />
        </div>
        <div>
          <label htmlFor={ids.text} className="text-sm font-medium">{t("lifecycle.itemText")}</label>
          <input id={ids.text} className={FIELD} value={text} onChange={(e) => setText(e.target.value)} minLength={5} />
        </div>
      </div>
      <label htmlFor={ids.reason} className="mt-2 block text-sm font-medium">{t("lifecycle.reason")}</label>
      <textarea id={ids.reason} className={FIELD} rows={2} minLength={10} value={reason} onChange={(e) => setReason(e.target.value)} />
      {back.isError ? <div className="mt-2"><ProblemNotice error={back.error} /></div> : null}
      <button type="button" className={`${BUTTON} mt-3`} disabled={back.isPending || reason.trim().length < 10 || code.trim().length === 0 || text.trim().length < 5} onClick={() => back.mutate()}>
        {t("lifecycle.returnSubmit")}
      </button>
    </div>
  );
}
