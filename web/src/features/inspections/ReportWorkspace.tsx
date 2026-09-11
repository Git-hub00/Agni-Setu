import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { fetchDocument, uploadFile, type DocumentVersion } from "../../api/applications";
import {
  OBSERVATION_RESULTS,
  saveReportDraft,
  submitReport,
  type ChecklistItem,
  type InspectionDetail,
  type InspectionReport,
  type Observation,
  type ObservationResult,
  type ReportReceipt,
} from "../../api/inspections";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";
import type { ReportDraftRecord, StoredPackage } from "../../offline/database";
import { addLocalEvidence, queueReportOperation, saveLocalDraft } from "../../offline/queue";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";
const SECONDARY = "inline-flex min-h-11 items-center rounded-md border border-border bg-surface px-4 font-medium text-ink hover:bg-canvas disabled:opacity-60";

/** "LOCAL" = bytes saved on this device only (docs/09 s.4); `id` is then the local blob id. */
type EvidenceRef = { id: string; name: string; scan_state: DocumentVersion["scan_state"] | "LOCAL" };
type Row = { result: ObservationResult | ""; note: string; evidence: EvidenceRef[] };

/** Offline context supplied by the detail page (B11): who is working, whether the API is
 *  reachable right now, the saved package (if any) and the last draft saved on this device. */
export interface OfflineContext {
  principalId: string;
  online: boolean;
  storedPackage: StoredPackage | null;
  localDraft: ReportDraftRecord | null;
}

const NOTE_REQUIRED: readonly ObservationResult[] = ["FAIL", "NOT_VERIFIED", "NOT_APPLICABLE"];

function initialRows(items: ChecklistItem[], draft: InspectionDetail["draft"], local: ReportDraftRecord | null): Record<string, Row> {
  const rows: Record<string, Row> = {};
  for (const item of items) rows[item.code] = { result: "", note: "", evidence: [] };
  const source: { item_code: string; result: string; note: string; document_version_ids: string[] }[] = draft?.observations ?? local?.observations ?? [];
  for (const o of source) {
    rows[o.item_code] = {
      result: o.result as ObservationResult,
      note: o.note,
      evidence: o.document_version_ids.map((id) => ({ id, name: id.slice(0, 8), scan_state: "CLEAN" })),
    };
  }
  if (!draft && local) {
    for (const marker of local.dirty_fields) {
      const [code, blobId] = marker.split(":");
      if (code && blobId && code in rows) rows[code].evidence.push({ id: blobId, name: t("sync.state.LOCAL_DRAFT"), scan_state: "LOCAL" });
    }
  }
  return rows;
}

function toObservations(rows: Record<string, Row>, items: ChecklistItem[]): Observation[] {
  return items
    .filter((item) => rows[item.code].result)
    .map((item) => {
      const row = rows[item.code];
      return {
        item_code: item.code,
        result: row.result as ObservationResult,
        note: row.note,
        document_version_ids: row.evidence.filter((e) => e.scan_state !== "LOCAL").map((e) => e.id),
      };
    });
}

/** UI-12: eight checklist items with PASS / FAIL / NOT_VERIFIED / NOT_APPLICABLE, notes,
 *  evidence per item, Save draft (API-045) and Submit report (API-047). A stale assignment or
 *  inspection version surfaces as a conflict notice with the server's current version. With an
 *  offline context the workspace can also save on this device and queue a frozen operation for
 *  the synchronisation centre (UI-13); an offline submit is never shown as received. */
export function ReportWorkspace({ inspection, etag, canSubmit, offline = null }: { inspection: InspectionDetail; etag: string; canSubmit: boolean; offline?: OfflineContext | null }) {
  const queryClient = useQueryClient();
  const items = inspection.checklist_items;
  const [rows, setRows] = useState<Record<string, Row>>(() => initialRows(items, inspection.draft, offline?.localDraft ?? null));
  const [summary, setSummary] = useState(inspection.draft?.summary ?? offline?.localDraft?.summary ?? "");
  const [queued, setQueued] = useState<string | null>(null);
  const [savedLocally, setSavedLocally] = useState<string | null>(null);
  const [declared, setDeclared] = useState(false);
  const [localRevision, setLocalRevision] = useState((inspection.draft?.local_revision ?? 0) + 1);
  // Stable per submit attempt: retries after an unknown outcome reuse the same operation id.
  const [operationId, setOperationId] = useState(() => crypto.randomUUID());
  const [receipt, setReceipt] = useState<ReportReceipt | null>(null);
  const ids = { summary: useId(), declaration: useId() };

  const update = (code: string, patch: Partial<Row>) => setRows((current) => ({ ...current, [code]: { ...current[code], ...patch } }));

  const save = useMutation({
    mutationFn: () => saveReportDraft(inspection, { observations: toObservations(rows, items), summary, local_revision: localRevision }, etag),
    onSuccess: () => setLocalRevision((r) => r + 1),
  });
  const submit = useMutation({
    mutationFn: () => submitReport(inspection, { observations: toObservations(rows, items), summary, declaration_accepted: declared, source_operation_id: operationId }, etag),
    onSuccess: async ({ data }) => {
      setReceipt(data);
      setOperationId(crypto.randomUUID());
      await queryClient.invalidateQueries({ queryKey: ["inspections"] });
      await queryClient.invalidateQueries({ queryKey: ["applications"] });
    },
  });
  const upload = useMutation({
    mutationFn: async ({ code, file }: { code: string; file: File }): Promise<{ code: string; ref: EvidenceRef }> => {
      if (offline && !offline.online) {
        // No API: keep the bytes on this device; they upload at sync time (docs/09 s.5 step 3).
        const local = await addLocalEvidence({ inspection_id: inspection.inspection_id, item_code: code, principal_id: offline.principalId, file, name: file.name, media_type: file.type });
        return { code, ref: { id: local.blob_id, name: file.name, scan_state: "LOCAL" } };
      }
      const version = await uploadFile("INSPECTION_EVIDENCE", inspection.inspection_id, `inspection-${code.toLowerCase()}`, file);
      return { code, ref: { id: version.document_version_id, name: version.original_name, scan_state: version.scan_state } };
    },
    onSuccess: ({ code, ref }) => update(code, { evidence: [...rows[code].evidence, ref] }),
  });
  const localRefs = (code: string) => rows[code].evidence.filter((e) => e.scan_state === "LOCAL").map((e) => `${code}:${e.id}`);
  const saveLocal = useMutation({
    mutationFn: async () => {
      if (!offline) throw new Error("offline context missing");
      const record = await saveLocalDraft({
        inspection_id: inspection.inspection_id,
        principal_id: offline.principalId,
        observations: toObservations(rows, items),
        summary,
        dirty_fields: items.flatMap((item) => localRefs(item.code)),
        captured_at: new Date().toISOString(),
      });
      return record;
    },
    onSuccess: (record) => setSavedLocally(record.saved_at),
  });
  const queue = useMutation({
    mutationFn: async () => {
      if (!offline?.storedPackage) throw new Error("no offline package saved for this attempt");
      return queueReportOperation({
        principal_id: offline.principalId,
        package: offline.storedPackage,
        observations: items
          .filter((item) => rows[item.code].result)
          .map((item) => ({
            item_code: item.code,
            result: rows[item.code].result as ObservationResult, // filtered above: never ""
            note: rows[item.code].note,
            blob_ids: rows[item.code].evidence.filter((e) => e.scan_state === "LOCAL").map((e) => e.id),
            document_version_ids: rows[item.code].evidence.filter((e) => e.scan_state !== "LOCAL").map((e) => e.id),
          })),
        summary,
        captured_at: new Date().toISOString(),
      });
    },
    onSuccess: (op) => setQueued(op.operation_id),
  });
  const refreshScans = useMutation({
    mutationFn: async () => {
      const pending = Object.entries(rows).flatMap(([code, row]) => row.evidence.filter((e) => e.scan_state === "QUARANTINED").map((e) => ({ code, e })));
      const results = await Promise.all(pending.map(async ({ code, e }) => ({ code, id: e.id, version: await fetchDocument(e.id) })));
      setRows((current) => {
        const next = { ...current };
        for (const { code, id, version } of results) {
          next[code] = { ...next[code], evidence: next[code].evidence.map((ev) => (ev.id === id ? { ...ev, scan_state: version.scan_state } : ev)) };
        }
        return next;
      });
      return results.length;
    },
  });

  const complete = items.every((item) => rows[item.code].result);
  const notesOk = items.every((item) => {
    const row = rows[item.code];
    return !row.result || !NOTE_REQUIRED.includes(row.result) || row.note.trim().length >= 10;
  });
  const pendingScans = Object.values(rows).some((row) => row.evidence.some((e) => e.scan_state === "QUARANTINED"));
  const hasLocalEvidence = Object.values(rows).some((row) => row.evidence.some((e) => e.scan_state === "LOCAL"));
  const online = offline?.online ?? true;
  const ready = canSubmit && online && complete && notesOk && summary.trim().length >= 10 && declared && !pendingScans && !hasLocalEvidence;
  const canQueue = offline?.storedPackage !== null && offline !== null && complete && notesOk && summary.trim().length >= 10 && declared;

  if (receipt) return <ReportView report={receipt.report} items={items} title={t("report.acceptedTitle")} receipt={receipt.receipt} />;
  if (queued) {
    return (
      <section className={CARD} aria-labelledby="report-queued" role="status">
        <h2 id="report-queued" className="text-base font-semibold">{t("sync.state.READY_TO_SUBMIT")}</h2>
        <p className="mt-2 text-sm">{t("sync.queuedReport")} <span className="text-muted">({queued.slice(0, 8)})</span></p>
      </section>
    );
  }

  return (
    <section className={CARD} aria-labelledby="report-workspace">
      <h2 id="report-workspace" className="text-base font-semibold">{t("report.title")}</h2>
      <p className="mt-1 text-sm text-muted">{t("report.help")}</p>
      <ol className="mt-4 flex flex-col gap-4">
        {items.map((item) => {
          const row = rows[item.code];
          const needsNote = row.result !== "" && NOTE_REQUIRED.includes(row.result);
          return (
            <li key={item.code} className="rounded-md border border-border p-4">
              <ObservationRow item={item} row={row} needsNote={needsNote} onChange={(patch) => update(item.code, patch)} onUpload={(file) => upload.mutate({ code: item.code, file })} uploading={upload.isPending && upload.variables.code === item.code} />
            </li>
          );
        })}
      </ol>
      <div className="mt-4">
        <label htmlFor={ids.summary} className="text-sm font-medium">{t("report.summary")}</label>
        <textarea id={ids.summary} className={FIELD} rows={3} value={summary} onChange={(e) => setSummary(e.target.value)} minLength={10} maxLength={4000} />
      </div>
      <div className="mt-3 flex items-start gap-2">
        <input id={ids.declaration} type="checkbox" className="mt-1 h-5 w-5" checked={declared} onChange={(e) => setDeclared(e.target.checked)} />
        <label htmlFor={ids.declaration} className="text-sm">{t("report.declaration")}</label>
      </div>
      {save.isError ? <div className="mt-3"><ProblemNotice error={save.error} /></div> : null}
      {submit.isError ? <div className="mt-3"><ProblemNotice error={submit.error} /></div> : null}
      {upload.isError ? <div className="mt-3"><ProblemNotice error={upload.error} /></div> : null}
      {pendingScans ? <p className="mt-3 text-sm text-muted">{t("report.pendingScans")}</p> : null}
      {saveLocal.isError ? <div className="mt-3"><ProblemNotice error={saveLocal.error} /></div> : null}
      {queue.isError ? <div className="mt-3"><ProblemNotice error={queue.error} /></div> : null}
      {offline && !offline.online ? <p role="status" className="mt-3 rounded-md bg-warning-soft p-2 text-sm text-warning">{t("sync.connectivity.OFFLINE")} · {offline.storedPackage ? t("sync.queuedHint") : t("sync.offlineNoPackage")}</p> : null}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button type="button" className={SECONDARY} disabled={save.isPending || !online} onClick={() => save.mutate()}>{t("report.saveDraft")}</button>
        {offline ? (
          <button type="button" className={SECONDARY} disabled={saveLocal.isPending} onClick={() => saveLocal.mutate()}>{t("sync.saveLocal")}</button>
        ) : null}
        {pendingScans && online ? (
          <button type="button" className={SECONDARY} disabled={refreshScans.isPending} onClick={() => refreshScans.mutate()}>{t("report.checkScans")}</button>
        ) : null}
        {online && !hasLocalEvidence ? (
          <button type="button" className={BUTTON} disabled={!ready || submit.isPending} onClick={() => submit.mutate()}>{t("report.submit")}</button>
        ) : null}
        {offline?.storedPackage ? (
          <button type="button" className={online && !hasLocalEvidence ? SECONDARY : BUTTON} disabled={!canQueue || queue.isPending} onClick={() => queue.mutate()}>{t("sync.queueReport")}</button>
        ) : null}
        {save.isSuccess ? <span className="text-sm text-muted">{t("report.draftSaved")} {new Date(save.data.saved_at).toLocaleTimeString()}</span> : null}
        {savedLocally ? <span className="text-sm text-muted">{t("sync.state.LOCAL_DRAFT")} {new Date(savedLocally).toLocaleTimeString()}</span> : null}
        {!canSubmit && online ? <span className="text-sm text-muted">{t("report.checkInFirst")}</span> : null}
      </div>
    </section>
  );
}

function ObservationRow({ item, row, needsNote, onChange, onUpload, uploading }: { item: ChecklistItem; row: Row; needsNote: boolean; onChange: (patch: Partial<Row>) => void; onUpload: (file: File) => void; uploading: boolean }) {
  const ids = { result: useId(), note: useId(), file: useId() };
  const options = OBSERVATION_RESULTS.filter((r) => r !== "NOT_APPLICABLE" || item.na_permitted);
  return (
    <div className="grid gap-3 sm:grid-cols-[1fr_220px]">
      <div>
        <p className="text-sm font-medium">
          <span className="font-semibold">{item.code}</span> {item.title}
          {item.mandatory ? <span className="ml-1 text-danger" title={t("report.mandatory")}>*</span> : null}
          {item.evidence_required ? <span className="ml-2 text-xs text-muted">{t("report.evidenceRequired")}</span> : null}
        </p>
        <label htmlFor={ids.note} className="mt-2 block text-xs text-muted">{needsNote ? t("report.noteRequired") : t("report.note")}</label>
        <textarea id={ids.note} className={FIELD} rows={2} value={row.note} onChange={(e) => onChange({ note: e.target.value })} maxLength={2000} aria-invalid={needsNote && row.note.trim().length < 10} />
        <ul className="mt-2 flex flex-wrap gap-2 text-xs">
          {row.evidence.map((e) => (
            <li key={e.id} className="rounded border border-border px-2 py-1">{e.name} · {e.scan_state}</li>
          ))}
        </ul>
      </div>
      <div className="flex flex-col gap-2">
        <label htmlFor={ids.result} className="text-xs text-muted">{t("report.result")}</label>
        <select id={ids.result} className={FIELD} value={row.result} onChange={(e) => onChange({ result: e.target.value as ObservationResult | "" })}>
          <option value="">{t("report.chooseResult")}</option>
          {options.map((r) => (
            <option key={r} value={r}>{t(`report.result.${r}`)}</option>
          ))}
        </select>
        <label htmlFor={ids.file} className="text-xs text-muted">{t("report.addEvidence")}</label>
        <input id={ids.file} type="file" accept="application/pdf,image/jpeg,image/png" className="text-xs" disabled={uploading} onChange={(e) => { const file = e.target.files?.[0]; if (file) onUpload(file); e.target.value = ""; }} />
      </div>
    </div>
  );
}

/** Read-only accepted report: observations, evidence hashes and the deterministic evaluation.
 *  No score is shown because none exists. */
export function ReportView({ report, items, title, receipt }: { report: InspectionReport; items: ChecklistItem[]; title: string; receipt?: ReportReceipt["receipt"] }) {
  const titles = new Map(items.map((i) => [i.code, i.title] as const));
  const evaluation = report.evaluation;
  return (
    <section className={CARD} aria-labelledby="report-view">
      <h2 id="report-view" className="text-base font-semibold">{title}</h2>
      <p className="mt-1 text-sm text-muted">
        {t("report.revision")} {report.revision_number} · {t("report.acceptedAt")} {new Date(report.accepted_at).toLocaleString()} · SHA-256 {report.sha256.slice(0, 12)}…
      </p>
      {receipt ? <p className="mt-1 text-sm">{t("report.caseNow")} {receipt.application_status}</p> : null}
      <div className={`mt-3 rounded-md border p-3 text-sm ${evaluation.eligible_for_review ? "border-border" : "border-danger"}`} role="status">
        <p className="font-medium">{evaluation.eligible_for_review ? t("report.eligible") : t("report.blocked")}</p>
        {evaluation.blockers.length > 0 ? (
          <ul className="mt-1 list-disc pl-5">
            {evaluation.blockers.map((b) => (
              <li key={`${b.code}-${b.item_code}`}>{b.item_code} · {b.message}</li>
            ))}
          </ul>
        ) : null}
        {evaluation.na_requiring_review.length > 0 ? <p className="mt-1 text-muted">{t("report.naReview")} {evaluation.na_requiring_review.join(", ")}</p> : null}
      </div>
      <table className="mt-3 w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-muted">
            <th className="py-1">{t("report.item")}</th>
            <th className="py-1">{t("report.result")}</th>
            <th className="py-1">{t("report.note")}</th>
            <th className="py-1">{t("report.evidence")}</th>
          </tr>
        </thead>
        <tbody>
          {report.observations.map((o) => (
            <tr key={o.item_code} className="border-t border-border align-top">
              <td className="py-1"><span className="font-medium">{o.item_code}</span> {titles.get(o.item_code)}</td>
              <td className="py-1">{t(`report.result.${o.result}`)}</td>
              <td className="py-1">{o.note || "—"}</td>
              <td className="py-1">{o.document_version_ids.length}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-sm">{report.summary}</p>
    </section>
  );
}
