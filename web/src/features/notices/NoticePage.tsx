import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link, useParams } from "react-router";

import { fetchDocument, requestDocumentAccess, type DocumentVersion } from "../../api/applications";
import {
  acceptInformation,
  findingsQuery,
  noticeQuery,
  reviewItem,
  submitResponse,
  uploadResponseEvidence,
  verifyFinding,
  type Finding,
  type NoticeDetail,
  type NoticeItem,
} from "../../api/notices";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";
const SECONDARY = "inline-flex min-h-11 items-center rounded-md border border-border bg-surface px-4 font-medium text-ink hover:bg-canvas disabled:opacity-60";

type EvidenceRef = { id: string; name: string; scan_state: DocumentVersion["scan_state"] };
type Draft = { explanation: string; evidence: EvidenceRef[] };

const ITEM_STATE_KEY: Record<NoticeItem["state"], "notice.state.OPEN" | "notice.state.RESPONSE_RECEIVED" | "notice.state.UNDER_REVIEW" | "notice.state.ACCEPTED" | "notice.state.RETURNED"> = {
  OPEN: "notice.state.OPEN",
  RESPONSE_RECEIVED: "notice.state.RESPONSE_RECEIVED",
  UNDER_REVIEW: "notice.state.UNDER_REVIEW",
  ACCEPTED: "notice.state.ACCEPTED",
  RETURNED: "notice.state.RETURNED",
};

/** UI-08: notice header (type, reason, deadline basis), item task list for the applicant with
 *  evidence upload + per-item responses, and the reviewer's accept/return + finding verification
 *  controls. "Response received" is never styled as verified. */
export function NoticePage() {
  const { applicationId = "", noticeId = "" } = useParams();
  const query = useQuery(noticeQuery(noticeId));
  if (query.isPending) return <p className="text-sm text-muted">{t("notice.loading")}</p>;
  if (query.isError) return <ProblemNotice error={query.error} />;
  const { notice, etag } = query.data;
  const actions = new Map(notice.allowed_actions.map((a) => [a.key, a] as const));
  const canRespond = actions.get("respond")?.enabled === true;
  const canReview = actions.get("review-item")?.enabled === true;
  const canVerify = actions.get("verify-finding")?.enabled === true;
  const canAccept = actions.get("accept-information")?.enabled === true;
  const reviewer = canReview || canVerify || notice.internal_note !== undefined;
  return (
    <div className="mx-auto flex max-w-[980px] flex-col gap-6">
      <div>
        <Link to={`/applications/${applicationId}`} className="text-sm text-primary">← {notice.public_reference ?? t("notice.backToCase")}</Link>
        <h1 className="mt-1 text-2xl font-semibold text-ink">
          {notice.type === "INFORMATION" ? t("notice.informationTitle") : t("notice.deficiencyTitle")} · {t("notice.round")} {notice.round_number}
        </h1>
        <p className="text-sm text-muted">{t(`notice.notice.${notice.state}` as "notice.notice.PUBLISHED")}{notice.due_at ? ` · ${t("notice.respondBy")} ${new Date(notice.due_at).toLocaleString()}` : ""}</p>
      </div>
      <section className={CARD} aria-labelledby="notice-reason">
        <h2 id="notice-reason" className="text-base font-semibold">{t("notice.reason")}</h2>
        <p className="mt-2 text-sm">{notice.public_reason}</p>
        <p className="mt-2 text-xs text-muted">{t("notice.deadlineBasis")} {notice.response_budget_minutes} {t("notice.minutes")}</p>
        {notice.superseded_by_id ? (
          <p role="alert" className="mt-3 rounded-md border border-warning bg-warning-soft p-3 text-sm">
            {t("notice.superseded")} <Link to={`/applications/${applicationId}/notices/${notice.superseded_by_id}`} className="text-primary">{t("notice.openCurrent")}</Link>
          </p>
        ) : null}
        {notice.internal_note ? <p className="mt-3 rounded-md bg-information-soft p-3 text-sm text-information">{t("notice.internalNote")} {notice.internal_note}</p> : null}
      </section>
      {canRespond ? <ResponseTasks notice={notice} etag={etag} /> : <ItemList notice={notice} reviewer={reviewer} />}
      {reviewer ? <ReviewerPanel notice={notice} etag={etag} applicationId={applicationId} canReview={canReview} canVerify={canVerify} canAccept={canAccept} /> : null}
    </div>
  );
}

function ItemList({ notice, reviewer }: { notice: NoticeDetail; reviewer: boolean }) {
  return (
    <section className={CARD} aria-labelledby="notice-items">
      <h2 id="notice-items" className="text-base font-semibold">{t("notice.items")}</h2>
      <ol className="mt-3 flex flex-col gap-3">
        {notice.items.map((item) => (
          <li key={item.notice_item_id} className="rounded-md border border-border p-4 text-sm">
            <ItemHeader item={item} />
            <ResponseHistory item={item} reviewer={reviewer} />
          </li>
        ))}
      </ol>
    </section>
  );
}

function ItemHeader({ item }: { item: NoticeItem }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div>
        <p className="font-medium">
          {item.code} · {item.title} {item.required ? <span className="text-danger" title={t("notice.required")}>*</span> : <span className="text-xs text-muted">({t("notice.optional")})</span>}
        </p>
        <p className="mt-1 text-muted">{item.description}</p>
        {item.public_guidance ? <p className="mt-1 text-xs text-muted">{item.public_guidance}</p> : null}
        <p className="mt-1 text-xs text-muted">{t("notice.acceptedEvidence")} {item.acceptable_evidence_types.join(", ")}</p>
        {item.finding_severity ? <p className="mt-1 text-xs text-muted">{t("notice.linkedFinding")} {item.finding_severity} · {item.finding_state}</p> : null}
      </div>
      <span className={`rounded-md px-2 py-1 text-xs ${item.state === "ACCEPTED" ? "bg-positive-soft text-positive" : item.state === "RETURNED" ? "bg-warning-soft text-warning" : "bg-canvas text-ink"}`}>{t(ITEM_STATE_KEY[item.state])}</span>
    </div>
  );
}

function ResponseHistory({ item, reviewer }: { item: NoticeItem; reviewer: boolean }) {
  const open = async (id: string) => {
    const url = await requestDocumentAccess(id, "PREVIEW");
    window.open(url, "_blank", "noopener");
  };
  if (item.responses.length === 0 && !item.reviewer_feedback) return null;
  return (
    <div className="mt-3 border-t border-border pt-3">
      {item.reviewer_feedback ? <p className="text-sm text-warning">{t("notice.reviewerFeedback")} {item.reviewer_feedback}</p> : null}
      <ul className="mt-1 flex flex-col gap-1 text-xs">
        {item.responses.map((r) => (
          <li key={r.response_revision_id}>
            <span className="font-medium">{t("notice.revision")} {r.number}</span> · {new Date(r.accepted_at).toLocaleString()} · {r.explanation}
            {r.document_version_ids.map((d) => (
              <button key={d} type="button" className="ml-2 text-primary" onClick={() => void open(d)}>{t("wizard.open")} {d.slice(0, 8)}</button>
            ))}
          </li>
        ))}
        {reviewer
          ? item.reviews.map((r) => (
              <li key={r.review_id} className="text-muted">{r.outcome} · {new Date(r.accepted_at).toLocaleString()} · {r.reason}</li>
            ))
          : null}
      </ul>
    </div>
  );
}

function ResponseTasks({ notice, etag }: { notice: NoticeDetail; etag: string }) {
  const queryClient = useQueryClient();
  const [drafts, setDrafts] = useState<Partial<Record<string, Draft>>>({});
  const [declared, setDeclared] = useState(false);
  const [operationId, setOperationId] = useState(() => crypto.randomUUID());
  const declarationId = useId();
  const EMPTY: Draft = { explanation: "", evidence: [] };
  const update = (id: string, patch: Partial<Draft>) => setDrafts((d) => ({ ...d, [id]: { ...(d[id] ?? EMPTY), ...patch } }));
  const upload = useMutation({
    mutationFn: async ({ item, file }: { item: NoticeItem; file: File }) => ({ item, version: await uploadResponseEvidence(notice.notice_id, item.code, file) }),
    onSuccess: ({ item, version }) =>
      setDrafts((d) => {
        const current = d[item.notice_item_id] ?? EMPTY;
        return { ...d, [item.notice_item_id]: { ...current, evidence: [...current.evidence, { id: version.document_version_id, name: version.original_name, scan_state: version.scan_state }] } };
      }),
  });
  const entries = Object.entries(drafts).flatMap(([id, d]) => (d ? [[id, d] as const] : []));
  const refreshScans = useMutation({
    mutationFn: async () => {
      const pending = entries.flatMap(([id, d]) => d.evidence.filter((e) => e.scan_state === "QUARANTINED").map((e) => ({ id, e })));
      const results = await Promise.all(pending.map(async ({ id, e }) => ({ id, doc: e.id, version: await fetchDocument(e.id) })));
      setDrafts((current) => {
        const next = { ...current };
        for (const { id, doc, version } of results) {
          const draft = next[id];
          if (draft) next[id] = { ...draft, evidence: draft.evidence.map((ev) => (ev.id === doc ? { ...ev, scan_state: version.scan_state } : ev)) };
        }
        return next;
      });
    },
  });
  const ready = entries.filter(([, d]) => d.explanation.trim().length >= 10);
  const pendingScans = entries.some(([, d]) => d.evidence.some((e) => e.scan_state === "QUARANTINED"));
  const submit = useMutation({
    mutationFn: () =>
      submitResponse(
        notice,
        ready.map(([id, d]) => ({ notice_item_id: id, explanation: d.explanation.trim(), document_version_ids: d.evidence.map((e) => e.id) })),
        etag,
        operationId,
      ),
    onSuccess: async () => {
      setDrafts({});
      setDeclared(false);
      setOperationId(crypto.randomUUID());
      await queryClient.invalidateQueries({ queryKey: ["notices"] });
      await queryClient.invalidateQueries({ queryKey: ["applications"] });
    },
  });
  const openItems = notice.items.filter((i) => i.state !== "ACCEPTED" && i.state !== "UNDER_REVIEW");
  return (
    <section className={CARD} aria-labelledby="notice-tasks">
      <h2 id="notice-tasks" className="text-base font-semibold">{t("notice.yourTasks")}</h2>
      <p className="mt-1 text-sm text-muted">{t("notice.tasksHelp")}</p>
      <ol className="mt-3 flex flex-col gap-4">
        {notice.items.map((item) => (
          <li key={item.notice_item_id} className="rounded-md border border-border p-4 text-sm">
            <ItemHeader item={item} />
            <ResponseHistory item={item} reviewer={false} />
            {openItems.includes(item) ? (
              <ResponseEditor item={item} draft={drafts[item.notice_item_id] ?? EMPTY} onChange={(patch) => update(item.notice_item_id, patch)} onUpload={(file) => upload.mutate({ item, file })} uploading={upload.isPending && upload.variables.item.notice_item_id === item.notice_item_id} />
            ) : null}
          </li>
        ))}
      </ol>
      <div className="mt-4 flex items-start gap-2">
        <input id={declarationId} type="checkbox" className="mt-1 h-5 w-5" checked={declared} onChange={(e) => setDeclared(e.target.checked)} />
        <label htmlFor={declarationId} className="text-sm">{t("notice.declaration")}</label>
      </div>
      {upload.isError ? <div className="mt-3"><ProblemNotice error={upload.error} /></div> : null}
      {submit.isError ? <div className="mt-3"><ProblemNotice error={submit.error} /></div> : null}
      {pendingScans ? <p className="mt-3 text-sm text-muted">{t("report.pendingScans")}</p> : null}
      <div className="mt-4 flex flex-wrap gap-3">
        {pendingScans ? <button type="button" className={SECONDARY} disabled={refreshScans.isPending} onClick={() => refreshScans.mutate()}>{t("report.checkScans")}</button> : null}
        <button type="button" className={BUTTON} disabled={ready.length === 0 || !declared || pendingScans || submit.isPending} onClick={() => submit.mutate()}>
          {t("notice.submitResponses")} {ready.length > 0 ? `(${ready.length})` : ""}
        </button>
        {submit.isSuccess ? <span className="text-sm text-positive">{t("notice.responseReceived")}</span> : null}
      </div>
    </section>
  );
}

function ResponseEditor({ item, draft, onChange, onUpload, uploading }: { item: NoticeItem; draft: Draft; onChange: (patch: Partial<Draft>) => void; onUpload: (file: File) => void; uploading: boolean }) {
  const ids = { text: useId(), file: useId() };
  return (
    <div className="mt-3 grid gap-3 border-t border-border pt-3 sm:grid-cols-[1fr_240px]">
      <div>
        <label htmlFor={ids.text} className="text-xs text-muted">{t("notice.explanation")}</label>
        <textarea id={ids.text} className={FIELD} rows={3} value={draft.explanation} onChange={(e) => onChange({ explanation: e.target.value })} minLength={10} maxLength={4000} />
      </div>
      <div>
        <label htmlFor={ids.file} className="text-xs text-muted">{t("notice.addEvidence")} ({item.acceptable_evidence_types.join(", ")})</label>
        <input id={ids.file} type="file" accept="application/pdf,image/jpeg,image/png" className="mt-1 text-xs" disabled={uploading} onChange={(e) => { const file = e.target.files?.[0]; if (file) onUpload(file); e.target.value = ""; }} />
        <ul className="mt-2 flex flex-wrap gap-2 text-xs">
          {draft.evidence.map((e) => (
            <li key={e.id} className="rounded border border-border px-2 py-1">{e.name} · {e.scan_state}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function ReviewerPanel({ notice, etag, applicationId, canReview, canVerify, canAccept }: { notice: NoticeDetail; etag: string; applicationId: string; canReview: boolean; canVerify: boolean; canAccept: boolean }) {
  const queryClient = useQueryClient();
  const findings = useQuery({ ...findingsQuery(applicationId), enabled: canVerify });
  const [reason, setReason] = useState("");
  const [target, setTarget] = useState<string>("");
  const [verifyOutcome, setVerifyOutcome] = useState<"VERIFIED_CLOSED" | "RETURNED" | "REINSPECTION_REQUIRED">("VERIFIED_CLOSED");
  const [citedDocs, setCitedDocs] = useState<string[]>([]);
  const ids = { reason: useId(), target: useId(), outcome: useId() };
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["notices"] });
    await queryClient.invalidateQueries({ queryKey: ["findings"] });
    await queryClient.invalidateQueries({ queryKey: ["applications"] });
  };
  const reviewable = notice.items.filter((i) => i.state === "RESPONSE_RECEIVED" || i.state === "UNDER_REVIEW");
  const selected: NoticeItem | undefined = notice.items.find((i) => i.notice_item_id === target) ?? reviewable.at(0);
  const finding: Finding | undefined = selected?.finding_id ? findings.data?.find((f) => f.finding_id === selected.finding_id) : undefined;
  const review = useMutation({
    mutationFn: (outcome: "ACCEPTED" | "RETURNED") => {
      if (!selected) throw new Error("no item selected");
      return reviewItem(notice, selected, { outcome, reason });
    },
    onSuccess: refresh,
  });
  const verify = useMutation({
    mutationFn: () => {
      if (!finding) throw new Error("no finding selected");
      return verifyFinding(finding, notice.application_version, { outcome: verifyOutcome, reason, response_revision_id: selected?.current_response_id ?? null, evidence_document_ids: citedDocs });
    },
    onSuccess: refresh,
  });
  const accept = useMutation({ mutationFn: () => acceptInformation(notice, reason, etag), onSuccess: refresh });
  const valid = reason.trim().length >= 10;
  const responseDocs = selected?.responses.at(-1)?.document_version_ids ?? [];
  if (!canReview && !canVerify && !canAccept) return null;
  return (
    <section className={CARD} aria-labelledby="notice-review">
      <h2 id="notice-review" className="text-base font-semibold">{t("notice.reviewTitle")}</h2>
      <p className="mt-1 text-sm text-muted">{t("notice.reviewHelp")}</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor={ids.target} className="text-sm font-medium">{t("notice.itemToReview")}</label>
          <select id={ids.target} className={FIELD} value={selected?.notice_item_id ?? ""} onChange={(e) => setTarget(e.target.value)}>
            {reviewable.length === 0 ? <option value="">{t("notice.nothingToReview")}</option> : null}
            {reviewable.map((i) => (
              <option key={i.notice_item_id} value={i.notice_item_id}>{i.code} · {i.title}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={ids.reason} className="text-sm font-medium">{t("notice.publicReason")}</label>
          <textarea id={ids.reason} className={FIELD} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} minLength={10} />
        </div>
        {canVerify && finding ? (
          <div className="sm:col-span-2 rounded-md border border-border p-3 text-sm">
            <p className="font-medium">{t("notice.findingVerification")} {finding.checklist_item_code} · {finding.severity} · {finding.state}</p>
            <label htmlFor={ids.outcome} className="mt-2 block text-xs text-muted">{t("notice.verificationOutcome")}</label>
            <select id={ids.outcome} className={FIELD} value={verifyOutcome} onChange={(e) => setVerifyOutcome(e.target.value as typeof verifyOutcome)}>
              <option value="VERIFIED_CLOSED">{t("notice.outcome.VERIFIED_CLOSED")}</option>
              <option value="RETURNED">{t("notice.outcome.RETURNED")}</option>
              <option value="REINSPECTION_REQUIRED">{t("notice.outcome.REINSPECTION_REQUIRED")}</option>
            </select>
            {responseDocs.length > 0 ? (
              <fieldset className="mt-2">
                <legend className="text-xs text-muted">{t("notice.citeEvidence")}</legend>
                {responseDocs.map((d) => (
                  <label key={d} className="mr-3 inline-flex items-center gap-1 text-xs">
                    <input type="checkbox" checked={citedDocs.includes(d)} onChange={(e) => setCitedDocs((c) => (e.target.checked ? [...c, d] : c.filter((x) => x !== d)))} /> {d.slice(0, 8)}
                  </label>
                ))}
              </fieldset>
            ) : null}
            <p className="mt-2 text-xs text-muted">{t("notice.mandatoryRule")}</p>
            <button type="button" className={`${BUTTON} mt-3`} disabled={!valid || verify.isPending} onClick={() => verify.mutate()}>{t("notice.recordVerification")}</button>
          </div>
        ) : null}
      </div>
      {review.isError ? <div className="mt-3"><ProblemNotice error={review.error} /></div> : null}
      {verify.isError ? <div className="mt-3"><ProblemNotice error={verify.error} /></div> : null}
      {accept.isError ? <div className="mt-3"><ProblemNotice error={accept.error} /></div> : null}
      <div className="mt-4 flex flex-wrap gap-3">
        {canReview && selected ? (
          <>
            <button type="button" className={BUTTON} disabled={!valid || review.isPending} onClick={() => review.mutate("ACCEPTED")}>{t("notice.acceptItem")}</button>
            <button type="button" className={SECONDARY} disabled={!valid || review.isPending} onClick={() => review.mutate("RETURNED")}>{t("notice.returnItem")}</button>
          </>
        ) : null}
        {canAccept ? (
          <button type="button" className={BUTTON} disabled={!valid || accept.isPending} onClick={() => accept.mutate()}>{t("notice.acceptInformation")}</button>
        ) : null}
      </div>
    </section>
  );
}
