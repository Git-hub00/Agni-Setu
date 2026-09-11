import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useId, useState } from "react";
import { Link, useParams } from "react-router";

import {
  applicationQuery,
  fetchDocument,
  requestDocumentAccess,
  uploadDocument,
  type CaseDetail,
  type DeclarationDraft,
  type DocumentVersion,
  type DraftFields,
  type Requirement,
  type SavedDraft,
} from "../../api/applications";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t, type MessageKey } from "../../locales";
import { useDraftAutosave, type Conflict } from "./useDraftAutosave";

const STEPS: MessageKey[] = ["wizard.step.service", "wizard.step.details", "wizard.step.documents", "wizard.step.review"];
const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";
const SECONDARY = "inline-flex min-h-11 items-center rounded-md border border-border bg-surface px-4 font-medium text-ink hover:bg-canvas disabled:opacity-60";

const DETAIL_FIELDS: { key: string; label: MessageKey; type?: "number" | "decimal" }[] = [
  { key: "beneficiary_name", label: "wizard.field.beneficiaryName" },
  { key: "display_name", label: "premises.field.displayName" },
  { key: "address_line1", label: "premises.field.address" },
  { key: "locality", label: "premises.field.locality" },
  { key: "ward_key", label: "premises.field.ward" },
  { key: "postal_code", label: "premises.field.postalCode" },
  { key: "category_key", label: "premises.field.category" },
  { key: "area_sqm", label: "premises.field.area", type: "decimal" },
  { key: "height_m", label: "premises.field.height", type: "decimal" },
  { key: "floor_count", label: "premises.field.floors", type: "number" },
  { key: "occupancy_count", label: "premises.field.occupancy", type: "number" },
];

/** UI-06: four-step wizard over a server DRAFT with serialised autosave, explicit conflict
 *  resolution, quarantined uploads and a frozen review. Saving never changes the case state;
 *  submission (TR-01) arrives with B06 and is shown as unavailable, never as a dead button. */
export function ApplicationWizardPage() {
  const { applicationId = "" } = useParams();
  const query = useQuery(applicationQuery(applicationId));
  if (query.isPending) {
    return <p className="text-sm text-muted">{t("wizard.loading")}</p>;
  }
  if (query.isError) {
    return <ProblemNotice error={query.error} />;
  }
  const { detail, etag } = query.data;
  if (detail.status !== "DRAFT" || !detail.draft) {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted">{t("wizard.notEditable")}</p>
        <Link to={`/applications/${detail.application_id}`} className="text-primary">{t("applications.view")}</Link>
      </div>
    );
  }
  return <Wizard key={`${detail.application_id}:${detail.draft.draft_revision}`} detail={detail} etag={etag} />;
}

function Wizard({ detail, etag: initialEtag }: { detail: CaseDetail; etag: string }) {
  const queryClient = useQueryClient();
  const draft = detail.draft!;
  const [step, setStep] = useState(1);
  const [fields, setFields] = useState<DraftFields>(draft.fields);
  const [declarations, setDeclarations] = useState<DeclarationDraft[]>(draft.declaration_drafts);
  const [links, setLinks] = useState<string[]>(draft.attachment_links);
  const [documents, setDocuments] = useState<DocumentVersion[]>(draft.documents);
  const [requirements, setRequirements] = useState<Requirement[]>(draft.requirements);
  const [blockers, setBlockers] = useState(draft.blockers);
  const [savedAt, setSavedAt] = useState(draft.saved_at);
  const [etag, setEtag] = useState(initialEtag);
  const [revision, setRevision] = useState(draft.draft_revision);

  const onSaved = useCallback(
    (saved: SavedDraft, newEtag: string) => {
      setEtag(newEtag);
      setRevision(saved.draft_revision);
      setFields(saved.fields);
      setDeclarations(saved.declaration_drafts);
      setLinks(saved.attachment_links);
      setDocuments(saved.documents);
      setRequirements(saved.requirements);
      setBlockers(saved.blockers);
      setSavedAt(saved.saved_at);
      queryClient.setQueryData(applicationQuery(detail.application_id).queryKey, (old) =>
        old ? { detail: { ...old.detail, draft: { ...old.detail.draft!, ...saved }, version: saved.version }, etag: newEtag } : old,
      );
    },
    [detail.application_id, queryClient],
  );

  const autosave = useDraftAutosave({ applicationId: detail.application_id, etag, draftRevision: revision, onSaved });

  const setField = (key: string, value: string) => {
    const typed = DETAIL_FIELDS.find((f) => f.key === key)?.type;
    const parsed = value === "" ? null : typed === "number" ? Number(value) : value;
    setFields((prev) => ({ ...prev, [key]: parsed }));
    autosave.schedule({ fields: { [key]: parsed } });
  };
  const toggleDeclaration = (code: string, version: string, accepted: boolean) => {
    const next = [...declarations.filter((d) => d.code !== code), { code, version, accepted }];
    setDeclarations(next);
    autosave.schedule({ declaration_drafts: next }, 0);
  };

  return (
    <div className="mx-auto flex max-w-[920px] flex-col gap-6">
      <div>
        <Link to="/applications" className="text-sm text-primary">← {t("applications.title")}</Link>
        <h1 className="mt-1 text-2xl font-semibold text-ink">{t("wizard.title")} · {detail.draft_reference}</h1>
      </div>
      <ol className="flex flex-wrap gap-2 text-sm" aria-label={t("wizard.steps")}>
        {STEPS.map((key, index) => {
          const n = index + 1;
          const current = n === step;
          return (
            <li key={key}>
              <button
                type="button"
                aria-current={current ? "step" : undefined}
                className={`min-h-11 rounded-md px-3 ${current ? "bg-primary text-white" : "border border-border bg-surface text-ink"}`}
                onClick={() => setStep(n)}
              >
                {n}. {t(key)}
              </button>
            </li>
          );
        })}
      </ol>
      <SaveIndicator state={autosave.state} savedAt={savedAt} error={autosave.error} onRetry={() => void autosave.retry()} />
      {autosave.conflict ? (
        <ConflictPanel
          conflict={autosave.conflict}
          applicationId={detail.application_id}
          onResolved={(keep, serverFields, newEtag, newRevision) => {
            setEtag(newEtag);
            setRevision(newRevision);
            if (keep === "server") setFields(serverFields);
            autosave.resolveConflict(keep, keep === "mine" ? autosave.conflict?.localFields ?? {} : serverFields, newEtag, newRevision);
          }}
        />
      ) : null}

      {step === 1 ? (
        <section className={CARD} aria-labelledby="wizard-step-1">
          <h2 id="wizard-step-1" className="text-base font-semibold">{t("wizard.step.service")}</h2>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-muted">{t("wizard.service")}</dt>
            <dd>{detail.service_key}</dd>
            <dt className="text-muted">{t("wizard.premises")}</dt>
            <dd>{detail.premises.display_name} · {detail.premises.locality}</dd>
            <dt className="text-muted">{t("applicability.policy")}</dt>
            <dd>{detail.policy.policy_number ? `v${detail.policy.policy_number}` : "-"} · {detail.policy.explanation}</dd>
          </dl>
        </section>
      ) : null}

      {step === 2 ? (
        <section className={CARD} aria-labelledby="wizard-step-2">
          <h2 id="wizard-step-2" className="text-base font-semibold">{t("wizard.step.details")}</h2>
          <form className="mt-4 grid gap-3 sm:grid-cols-2" onSubmit={(e) => e.preventDefault()} noValidate>
            {DETAIL_FIELDS.map((f) => (
              <FieldInput key={f.key} spec={f} value={fields[f.key]} onChange={(v) => setField(f.key, v)} />
            ))}
          </form>
          <h3 className="mt-6 text-sm font-semibold">{t("wizard.declarations")}</h3>
          <ul className="mt-2 flex flex-col gap-2">
            {draft.declarations.map((d) => {
              const accepted = declarations.find((x) => x.code === d.code)?.accepted === true;
              const id = `decl-${d.code}`;
              return (
                <li key={d.code} className="flex items-start gap-2 text-sm">
                  <input id={id} type="checkbox" className="mt-1 size-5" checked={accepted} onChange={(e) => toggleDeclaration(d.code, d.version, e.target.checked)} />
                  <label htmlFor={id}>{d.text}</label>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {step === 3 ? (
        <DocumentsStep
          applicationId={detail.application_id}
          requirements={requirements}
          documents={documents}
          links={links}
          onLinked={(nextLinks) => {
            setLinks(nextLinks);
            autosave.schedule({ attachment_links: nextLinks }, 0);
          }}
          onDocumentsChanged={(docs) => setDocuments(docs)}
        />
      ) : null}

      {step === 4 ? (
        <section className={CARD} aria-labelledby="wizard-step-4">
          <h2 id="wizard-step-4" className="text-base font-semibold">{t("wizard.step.review")}</h2>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
            {DETAIL_FIELDS.map((f) => (
              <FragmentRow key={f.key} label={t(f.label)} value={fields[f.key]} />
            ))}
          </dl>
          <h3 className="mt-4 text-sm font-semibold">{t("wizard.requirements")}</h3>
          <ul className="mt-1 text-sm">
            {requirements.map((r) => (
              <li key={r.code}>{r.label}: {t(requirementStatusKey(r.status))}</li>
            ))}
          </ul>
          {blockers.length > 0 ? (
            <div className="mt-4 rounded-md border border-warning bg-warning-soft p-3 text-sm text-warning">
              <p className="font-medium">{t("wizard.blockersTitle")}</p>
              <ul className="mt-1 list-disc pl-5">
                {blockers.map((b) => (
                  <li key={`${b.code}:${b.pointer}`}>{b.code} <code>{b.pointer}</code></li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="mt-4 rounded-md bg-positive-soft p-3 text-sm text-positive">{t("wizard.readyForSubmission")}</p>
          )}
          <p className="mt-4 text-sm text-muted">{t("wizard.submitLater")}</p>
        </section>
      ) : null}

      <div className="sticky bottom-0 flex flex-wrap items-center justify-between gap-3 border-t border-border bg-canvas py-3">
        <button type="button" className={SECONDARY} disabled={step === 1} onClick={() => setStep((s) => Math.max(1, s - 1))}>
          {t("wizard.back")}
        </button>
        <div className="flex gap-3">
          <button type="button" className={SECONDARY} onClick={() => void autosave.saveNow()}>
            {t("wizard.saveAndExit")}
          </button>
          {step < 4 ? (
            <button type="button" className={BUTTON} onClick={() => setStep((s) => Math.min(4, s + 1))}>
              {t("wizard.next")}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  return typeof value === "number" || typeof value === "string" ? String(value) : "-";
}

function FragmentRow({ label, value }: { label: string; value: unknown }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd>{display(value)}</dd>
    </>
  );
}

function FieldInput({ spec, value, onChange }: { spec: (typeof DETAIL_FIELDS)[number]; value: unknown; onChange: (v: string) => void }) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="text-sm font-medium">{t(spec.label)}</label>
      <input
        id={id}
        className={FIELD}
        type={spec.type === "number" ? "number" : "text"}
        inputMode={spec.type ? "decimal" : undefined}
        value={value === null || value === undefined ? "" : display(value)}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

function requirementStatusKey(status: Requirement["status"]): MessageKey {
  switch (status) {
    case "SATISFIED":
      return "wizard.req.satisfied";
    case "PENDING_SCAN":
      return "wizard.req.pending";
    case "REJECTED":
      return "wizard.req.rejected";
    default:
      return "wizard.req.missing";
  }
}

function SaveIndicator({ state, savedAt, error, onRetry }: { state: string; savedAt: string | null; error: unknown; onRetry: () => void }) {
  const label: Record<string, MessageKey> = {
    idle: "wizard.save.idle",
    dirty: "wizard.save.dirty",
    saving: "wizard.save.saving",
    saved: "wizard.save.saved",
    conflict: "wizard.save.conflict",
    error: "wizard.save.error",
  };
  return (
    <div role="status" aria-live="polite" data-save-state={state} className="flex flex-wrap items-center gap-3 text-sm text-muted">
      <span>{t(label[state] ?? "wizard.save.idle")}</span>
      {savedAt ? <span>· {t("wizard.save.at")} {new Date(savedAt).toLocaleTimeString()}</span> : null}
      {state === "error" ? (
        <>
          <button type="button" className="min-h-11 rounded-md border border-border px-3" onClick={onRetry}>{t("wizard.save.retry")}</button>
          <ProblemNotice error={error} />
        </>
      ) : null}
    </div>
  );
}

function ConflictPanel({
  conflict,
  applicationId,
  onResolved,
}: {
  conflict: Conflict;
  applicationId: string;
  onResolved: (keep: "server" | "mine", serverFields: DraftFields, etag: string, revision: number) => void;
}) {
  const queryClient = useQueryClient();
  const refresh = useMutation({
    mutationFn: async () => {
      const fresh = await queryClient.fetchQuery(applicationQuery(applicationId));
      return fresh;
    },
  });
  const resolve = (keep: "server" | "mine") => {
    refresh.mutate(undefined, {
      onSuccess: (fresh) => {
        onResolved(keep, fresh.detail.draft?.fields ?? {}, fresh.etag, fresh.detail.draft?.draft_revision ?? conflict.currentDraftRevision);
      },
    });
  };
  return (
    <div role="alert" className="rounded-md border border-warning bg-warning-soft p-4 text-sm">
      <p className="font-medium text-warning">{t("wizard.conflict.title")}</p>
      <p className="mt-1 text-ink">{t("wizard.conflict.body")}</p>
      {conflict.changedKeys.length > 0 ? (
        <table className="mt-3 w-full text-left">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-muted">
              <th scope="col">{t("wizard.conflict.field")}</th>
              <th scope="col">{t("wizard.conflict.server")}</th>
              <th scope="col">{t("wizard.conflict.mine")}</th>
            </tr>
          </thead>
          <tbody>
            {conflict.changedKeys.map((key) => (
              <tr key={key} className="border-t border-border">
                <td className="py-1 font-medium">{key}</td>
                <td className="py-1">{String(conflict.serverFields[key] ?? "-")}</td>
                <td className="py-1">{String(conflict.localFields[key] ?? "-")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <div className="mt-3 flex gap-3">
        <button type="button" className={SECONDARY} disabled={refresh.isPending} onClick={() => resolve("server")}>{t("wizard.conflict.useServer")}</button>
        <button type="button" className={BUTTON} disabled={refresh.isPending} onClick={() => resolve("mine")}>{t("wizard.conflict.keepMine")}</button>
      </div>
      {refresh.isError ? <ProblemNotice error={refresh.error} /> : null}
    </div>
  );
}

function DocumentsStep({
  applicationId,
  requirements,
  documents,
  links,
  onLinked,
  onDocumentsChanged,
}: {
  applicationId: string;
  requirements: Requirement[];
  documents: DocumentVersion[];
  links: string[];
  onLinked: (links: string[]) => void;
  onDocumentsChanged: (docs: DocumentVersion[]) => void;
}) {
  const [uploading, setUploading] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<unknown>(null);
  const pendingIds = documents.filter((d) => d.scan_state === "QUARANTINED").map((d) => d.document_version_id);

  // Poll quarantined versions every 2 s until the scan verdict lands (worker owns the verdict).
  useEffect(() => {
    if (pendingIds.length === 0) return;
    const handle = window.setInterval(() => {
      void Promise.all(pendingIds.map((id) => fetchDocument(id))).then((fresh) => {
        const byId = new Map(fresh.map((d) => [d.document_version_id, d]));
        onDocumentsChanged(documents.map((d) => byId.get(d.document_version_id) ?? d));
      });
    }, 2000);
    return () => window.clearInterval(handle);
  }, [pendingIds, documents, onDocumentsChanged]);

  const onPick = async (code: string, file: File | null) => {
    if (!file) return;
    setUploading(code);
    setUploadError(null);
    try {
      const version = await uploadDocument(applicationId, code, file);
      onDocumentsChanged([...documents, version]);
      onLinked([...links.filter((id) => documents.find((d) => d.document_version_id === id)?.requirement_code !== code), version.document_version_id]);
    } catch (cause) {
      setUploadError(cause);
    } finally {
      setUploading(null);
    }
  };
  const open = async (id: string) => {
    const url = await requestDocumentAccess(id, "PREVIEW");
    window.open(url, "_blank", "noopener");
  };

  return (
    <section className={CARD} aria-labelledby="wizard-step-3">
      <h2 id="wizard-step-3" className="text-base font-semibold">{t("wizard.step.documents")}</h2>
      <p className="mt-1 text-sm text-muted">{t("wizard.documents.help")}</p>
      {uploadError ? <div className="mt-3"><ProblemNotice error={uploadError} /></div> : null}
      <ul className="mt-4 flex flex-col gap-4">
        {requirements.map((req) => {
          const linked = documents.filter((d) => links.includes(d.document_version_id) && d.requirement_code === req.code);
          const inputId = `file-${req.code}`;
          return (
            <li key={req.code} className="rounded-md border border-border p-3" data-requirement={req.code} data-status={req.status}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="font-medium">{req.label} {req.required ? <span className="text-danger">*</span> : <span className="text-xs text-muted">({t("wizard.optional")})</span>}</p>
                  <p className="text-xs text-muted">{t(requirementStatusKey(req.status))}</p>
                </div>
                <label htmlFor={inputId} className={SECONDARY}>
                  {uploading === req.code ? t("wizard.uploading") : linked.length ? t("wizard.replace") : t("wizard.upload")}
                  <input
                    id={inputId}
                    type="file"
                    className="sr-only"
                    accept="application/pdf,image/jpeg,image/png"
                    disabled={uploading !== null}
                    onChange={(e) => void onPick(req.code, e.target.files?.[0] ?? null)}
                  />
                </label>
              </div>
              {linked.length > 0 ? (
                <ul className="mt-2 text-sm">
                  {linked.map((d) => (
                    <li key={d.document_version_id} className="flex flex-wrap items-center gap-3">
                      <span>{d.original_name} · {(d.size_bytes / 1024).toFixed(0)} KB · {d.scan_state}</span>
                      {d.scan_state === "CLEAN" ? (
                        <button type="button" className="text-primary" onClick={() => void open(d.document_version_id)}>{t("wizard.open")}</button>
                      ) : null}
                      {d.scan_state === "REJECTED" ? <span className="text-danger">{d.scan_detail}</span> : null}
                      <button type="button" className="text-muted" onClick={() => onLinked(links.filter((id) => id !== d.document_version_id))}>{t("wizard.remove")}</button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
