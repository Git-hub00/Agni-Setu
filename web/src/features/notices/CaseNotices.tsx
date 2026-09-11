import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link } from "react-router";

import type { CaseDetail } from "../../api/applications";
import {
  completeCorrections,
  findingsQuery,
  publishNotice,
  requireReinspection,
  type NoticeItemInput,
} from "../../api/notices";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";
const SECONDARY = "inline-flex min-h-11 items-center rounded-md border border-border bg-surface px-4 font-medium text-ink hover:bg-canvas disabled:opacity-60";
const EVIDENCE_TYPES = ["DOCUMENT", "PHOTOGRAPH", "TEST_CERTIFICATE", "INVOICE_OR_RECEIPT", "WRITTEN_EXPLANATION"] as const;

/** Case detail: notices tab content (both audiences) and the finding summary for staff. */
export function NoticesSection({ detail }: { detail: CaseDetail }) {
  if (detail.notices.length === 0 && !detail.findings_summary) return null;
  return (
    <section className={CARD} aria-labelledby="case-notices">
      <h2 id="case-notices" className="text-base font-semibold">{t("detail.notices")}</h2>
      {detail.notices.length > 0 ? (
        <ul className="mt-3 flex flex-col gap-1 text-sm">
          {detail.notices.map((n) => (
            <li key={n.notice_id} className="flex flex-wrap items-center gap-3">
              <Link to={`/applications/${detail.application_id}/notices/${n.notice_id}`} className="text-primary">
                {n.type === "INFORMATION" ? t("notice.informationTitle") : t("notice.deficiencyTitle")} · {t("detail.noticeRound")} {n.round_number}
              </Link>
              <span className="text-muted">{n.state}</span>
              <span className="text-muted">{n.open_items}/{n.items_total} {t("detail.openItems")}</span>
              {n.due_at ? <span className="text-muted">{t("notice.respondBy")} {new Date(n.due_at).toLocaleString()}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {detail.findings_summary ? (
        <p className="mt-3 text-sm text-muted">
          {t("detail.findings")}: {detail.findings_summary.open_mandatory} / {detail.findings_summary.open_advisory} / {detail.findings_summary.verified_closed} ({t("detail.findingsSummary")})
          {detail.findings_summary.reinspection_outstanding.length > 0 ? ` · ${t("notice.outcome.REINSPECTION_REQUIRED")}: ${detail.findings_summary.reinspection_outstanding.join(", ")}` : ""}
        </p>
      ) : null}
    </section>
  );
}

type ItemDraft = { code: string; title: string; description: string; required: boolean; evidence: string };

const EMPTY_ITEM: ItemDraft = { code: "INFO-01", title: "", description: "", required: true, evidence: "DOCUMENT" };

/** Supervisor notice actions on the case: TR-03 request information (item builder), TR-07 publish
 *  deficiencies (one item per open finding), TR-08 complete corrections and TR-09 reinspection.
 *  Buttons follow the server's allowed_actions; the server rechecks every guard. */
export function NoticeActions({ detail, etag }: { detail: CaseDetail; etag: string }) {
  const queryClient = useQueryClient();
  const actions = new Map(detail.allowed_actions.map((a) => [a.key, a] as const));
  const canRequest = actions.get("request-information")?.enabled === true;
  const canDeficiencies = actions.get("issue-deficiencies")?.enabled === true;
  const canComplete = actions.get("complete-corrections")?.enabled === true;
  const canReinspect = actions.get("require-reinspection")?.enabled === true;
  const findings = useQuery({ ...findingsQuery(detail.application_id), enabled: canDeficiencies || canReinspect });
  const [reason, setReason] = useState("");
  const [internal, setInternal] = useState("");
  const [items, setItems] = useState<ItemDraft[]>([EMPTY_ITEM]);
  const [selected, setSelected] = useState<string[]>([]);
  const [previous, setPrevious] = useState("");
  const ids = { reason: useId(), internal: useId(), previous: useId() };
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["applications"] });
    await queryClient.invalidateQueries({ queryKey: ["notices"] });
    await queryClient.invalidateQueries({ queryKey: ["findings"] });
    await queryClient.invalidateQueries({ queryKey: ["inspections"] });
  };
  const toInputs = (drafts: ItemDraft[]): NoticeItemInput[] =>
    drafts.map((d) => ({ code: d.code.trim().toUpperCase(), title: d.title.trim(), description: d.description.trim(), required: d.required, acceptable_evidence_types: [d.evidence] }));
  const request = useMutation({
    mutationFn: () => publishNotice(detail.application_id, { type: "INFORMATION", public_reason: reason, internal_note: internal || undefined, items: toInputs(items) }, etag),
    onSuccess: refresh,
  });
  const openFindings = (findings.data ?? []).filter((f) => f.state !== "VERIFIED_CLOSED");
  const deficiencies = useMutation({
    mutationFn: () =>
      publishNotice(
        detail.application_id,
        {
          type: "DEFICIENCY",
          public_reason: reason,
          internal_note: internal || undefined,
          items: openFindings.map((f) => ({
            code: `DEF-${f.checklist_item_code}`,
            title: `Correct checklist item ${f.checklist_item_code}`,
            description: f.description.length >= 10 ? f.description : `${f.description} (see the inspection report)`,
            required: f.severity === "MANDATORY",
            acceptable_evidence_types: ["PHOTOGRAPH", "WRITTEN_EXPLANATION"],
            finding_id: f.finding_id,
          })),
        },
        etag,
      ),
    onSuccess: refresh,
  });
  const complete = useMutation({ mutationFn: () => completeCorrections(detail.application_id, reason, etag), onSuccess: refresh });
  const reinspect = useMutation({
    mutationFn: () => requireReinspection(detail.application_id, { finding_ids: selected, reason, previous_inspection_id: previous }, etag),
    onSuccess: refresh,
  });
  if (!canRequest && !canDeficiencies && !canComplete && !canReinspect) return null;
  const valid = reason.trim().length >= 10;
  const itemsValid = items.every((i) => /^[A-Z][A-Z0-9_-]{1,39}$/.test(i.code.trim().toUpperCase()) && i.title.trim().length >= 5 && i.description.trim().length >= 10);
  const completedAttempts = detail.inspections.filter((i) => i.status === "COMPLETED");
  const error = request.error ?? deficiencies.error ?? complete.error ?? reinspect.error;
  return (
    <section className={CARD} aria-labelledby="notice-actions">
      <h2 id="notice-actions" className="text-base font-semibold">{t("detail.notices")} · {t("detail.staffActions")}</h2>
      <p className="mt-1 text-sm text-muted">{t("detail.noticeHelp")}</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor={ids.reason} className="text-sm font-medium">{t("detail.publicReason")}</label>
          <textarea id={ids.reason} className={FIELD} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} minLength={10} />
        </div>
        <div>
          <label htmlFor={ids.internal} className="text-sm font-medium">{t("detail.internalNote")}</label>
          <textarea id={ids.internal} className={FIELD} rows={2} value={internal} onChange={(e) => setInternal(e.target.value)} />
        </div>
      </div>
      {canRequest ? (
        <div className="mt-4 flex flex-col gap-3">
          {items.map((item, index) => (
            <ItemEditor key={index} item={item} onChange={(patch) => setItems((all) => all.map((x, i) => (i === index ? { ...x, ...patch } : x)))} onRemove={items.length > 1 ? () => setItems((all) => all.filter((_, i) => i !== index)) : undefined} />
          ))}
          <div className="flex flex-wrap gap-3">
            <button type="button" className={SECONDARY} onClick={() => setItems((all) => [...all, { ...EMPTY_ITEM, code: `INFO-${String(all.length + 1).padStart(2, "0")}` }])}>{t("detail.addItem")}</button>
            <button type="button" className={BUTTON} disabled={!valid || !itemsValid || request.isPending} onClick={() => request.mutate()}>{t("detail.requestInformation")}</button>
          </div>
        </div>
      ) : null}
      {canDeficiencies ? (
        <div className="mt-4 flex flex-col gap-2">
          <ul className="text-sm">
            {openFindings.map((f) => (
              <li key={f.finding_id}>{f.checklist_item_code} · {f.severity} · {f.state} · {f.description}</li>
            ))}
          </ul>
          <button type="button" className={BUTTON} disabled={!valid || openFindings.length === 0 || deficiencies.isPending} onClick={() => deficiencies.mutate()}>{t("detail.issueDeficiencies")}</button>
        </div>
      ) : null}
      {canReinspect ? (
        <div className="mt-4 flex flex-col gap-2">
          <fieldset>
            <legend className="text-sm font-medium">{t("detail.selectFindings")}</legend>
            {openFindings.map((f) => (
              <label key={f.finding_id} className="mr-4 inline-flex items-center gap-1 text-sm">
                <input type="checkbox" checked={selected.includes(f.finding_id)} onChange={(e) => setSelected((s) => (e.target.checked ? [...s, f.finding_id] : s.filter((x) => x !== f.finding_id)))} /> {f.checklist_item_code}
              </label>
            ))}
          </fieldset>
          <label htmlFor={ids.previous} className="text-sm font-medium">{t("detail.previousInspection")}</label>
          <select id={ids.previous} className={FIELD} value={previous} onChange={(e) => setPrevious(e.target.value)}>
            <option value="">-</option>
            {completedAttempts.map((i) => (
              <option key={i.inspection_id} value={i.inspection_id}>{t("queue.attempt")} {i.attempt_number}</option>
            ))}
          </select>
          <button type="button" className={SECONDARY} disabled={!valid || selected.length === 0 || !previous || reinspect.isPending} onClick={() => reinspect.mutate()}>{t("detail.requireReinspection")}</button>
        </div>
      ) : null}
      {canComplete ? (
        <div className="mt-4">
          <button type="button" className={BUTTON} disabled={!valid || complete.isPending} onClick={() => complete.mutate()}>{t("detail.completeCorrections")}</button>
        </div>
      ) : null}
      {error ? <div className="mt-3"><ProblemNotice error={error} /></div> : null}
    </section>
  );
}

function ItemEditor({ item, onChange, onRemove }: { item: ItemDraft; onChange: (patch: Partial<ItemDraft>) => void; onRemove?: () => void }) {
  const ids = { code: useId(), title: useId(), description: useId(), required: useId(), evidence: useId() };
  return (
    <div className="grid gap-2 rounded-md border border-border p-3 sm:grid-cols-[120px_1fr_160px]">
      <div>
        <label htmlFor={ids.code} className="text-xs text-muted">{t("detail.itemCode")}</label>
        <input id={ids.code} className={FIELD} value={item.code} onChange={(e) => onChange({ code: e.target.value })} />
      </div>
      <div>
        <label htmlFor={ids.title} className="text-xs text-muted">{t("detail.itemTitle")}</label>
        <input id={ids.title} className={FIELD} value={item.title} onChange={(e) => onChange({ title: e.target.value })} minLength={5} maxLength={200} />
      </div>
      <div>
        <label htmlFor={ids.evidence} className="text-xs text-muted">{t("notice.acceptedEvidence")}</label>
        <select id={ids.evidence} className={FIELD} value={item.evidence} onChange={(e) => onChange({ evidence: e.target.value })}>
          {EVIDENCE_TYPES.map((x) => (
            <option key={x} value={x}>{x}</option>
          ))}
        </select>
      </div>
      <div className="sm:col-span-3">
        <label htmlFor={ids.description} className="text-xs text-muted">{t("detail.itemDescription")}</label>
        <textarea id={ids.description} className={FIELD} rows={2} value={item.description} onChange={(e) => onChange({ description: e.target.value })} minLength={10} />
      </div>
      <div className="flex items-center gap-4 sm:col-span-3">
        <label htmlFor={ids.required} className="inline-flex items-center gap-2 text-sm">
          <input id={ids.required} type="checkbox" checked={item.required} onChange={(e) => onChange({ required: e.target.checked })} /> {t("detail.itemRequired")}
        </label>
        {onRemove ? <button type="button" className="text-sm text-danger" onClick={onRemove}>{t("detail.removeItem")}</button> : null}
      </div>
    </div>
  );
}
