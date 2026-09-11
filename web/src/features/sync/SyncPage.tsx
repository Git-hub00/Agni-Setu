import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useId, useState } from "react";
import { Link } from "react-router";

import { proposeConflict } from "../../api/offline";
import { ProblemNotice } from "../../app/ProblemNotice";
import { ensureDeviceMeta, offlineDb, type QueuedOperation, type StoredConflict, type StoredPackage, type StoredReceipt } from "../../offline/database";
import { probeConnectivity } from "../../offline/connectivity";
import { liveSyncDeps } from "../../offline/deps";
import { groupByState, listOperations, updateOperation } from "../../offline/queue";
import { syncAll, type SyncReport } from "../../offline/sync";
import { useSession } from "../identity/useSession";
import { t, type MessageKey } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-4 shadow-[var(--shadow-card)]";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";
const SECONDARY = "inline-flex min-h-11 items-center rounded-md border border-border bg-surface px-4 font-medium text-ink hover:bg-canvas disabled:opacity-60";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 text-sm text-ink";

const GROUP_LABEL: Record<keyof ReturnType<typeof groupByState>, MessageKey> = {
  NOT_UPLOADED: "sync.group.notUploaded",
  WAITING_FOR_SCAN: "sync.group.waitingScan",
  READY: "sync.group.ready",
  CONFLICT: "sync.group.conflicts",
  ACCEPTED: "sync.group.accepted",
};

const STATE_LABEL: Record<QueuedOperation["state"], MessageKey> = {
  LOCAL_DRAFT: "sync.state.LOCAL_DRAFT",
  WAITING_FOR_UPLOAD: "sync.state.WAITING_FOR_UPLOAD",
  WAITING_FOR_SCAN: "sync.state.WAITING_FOR_SCAN",
  READY_TO_SUBMIT: "sync.state.READY_TO_SUBMIT",
  SUBMITTING: "sync.state.SUBMITTING",
  ACCEPTED: "sync.state.ACCEPTED",
  CONFLICT: "sync.state.CONFLICT",
};

const CONNECTIVITY_LABEL: Record<"ONLINE" | "OFFLINE" | "SERVER_UNAVAILABLE" | "SIGN_IN_NEEDED", MessageKey> = {
  ONLINE: "sync.connectivity.ONLINE",
  OFFLINE: "sync.connectivity.OFFLINE",
  SERVER_UNAVAILABLE: "sync.connectivity.SERVER_UNAVAILABLE",
  SIGN_IN_NEEDED: "sync.connectivity.SIGN_IN_NEEDED",
};

interface LocalView {
  operations: QueuedOperation[];
  packages: Map<string, StoredPackage>;
  receipts: Map<string, StoredReceipt>;
  conflicts: Map<string, StoredConflict>;
  evidenceBytes: Map<string, number>;
}

async function loadLocal(principalId: string, authzEpoch: number): Promise<LocalView> {
  // Identity switch on a shared device purges the previous principal's local data (docs/09 s.9).
  await ensureDeviceMeta(principalId, authzEpoch);
  const db = offlineDb();
  const operations = await listOperations(principalId);
  const packages = new Map((await db.packages.where("principal_id").equals(principalId).toArray()).map((p) => [p.inspection_id, p] as const));
  const receipts = new Map((await db.receipts.where("principal_id").equals(principalId).toArray()).map((r) => [r.operation_id, r] as const));
  const conflicts = new Map((await db.conflicts.where("principal_id").equals(principalId).toArray()).map((c) => [c.operation_id, c] as const));
  const evidenceBytes = new Map<string, number>();
  for (const e of await db.local_evidence.where("principal_id").equals(principalId).toArray()) {
    evidenceBytes.set(e.inspection_id, (evidenceBytes.get(e.inspection_id) ?? 0) + e.size);
  }
  return { operations, packages, receipts, conflicts, evidenceBytes };
}

/** UI-13: the synchronisation centre. Groups local operations by state, shows exactly where
 *  each one is (this device / server draft / received), runs the explicit foreground sync
 *  (uploads then manifest) and opens conflicts side by side. Success is never shown before a
 *  stored receipt. */
export function SyncPage() {
  const { principal } = useSession();
  const principalId = principal?.id ?? "";
  const queryClient = useQueryClient();
  const authzEpoch = principal?.authz_epoch ?? 0;
  const local = useQuery({ queryKey: ["offline", "local", principalId] as const, queryFn: () => loadLocal(principalId, authzEpoch), enabled: principalId !== "" });
  const connectivity = useQuery({ queryKey: ["offline", "connectivity"] as const, queryFn: probeConnectivity, refetchInterval: 30000 });
  const [lastReport, setLastReport] = useState<SyncReport | null>(null);
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["offline"] });
    await queryClient.invalidateQueries({ queryKey: ["inspections"] });
  };
  const sync = useMutation({
    mutationFn: (only?: string) => syncAll(principalId, liveSyncDeps, only),
    onSuccess: async (report) => {
      setLastReport(report);
      await refresh();
    },
  });
  if (!principal) return <p className="text-sm text-muted">{t("sync.signIn")}</p>;
  const view = local.data;
  const groups = view ? groupByState(view.operations) : null;
  const pending = view ? view.operations.filter((o) => o.state !== "ACCEPTED" && o.state !== "CONFLICT").length : 0;
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-ink">{t("sync.title")}</h1>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          {connectivity.data ? (
            <span role="status" className={`rounded-md px-2 py-0.5 ${connectivity.data.state === "ONLINE" ? "bg-positive-soft text-positive" : "bg-warning-soft text-warning"}`}>
              {t(CONNECTIVITY_LABEL[connectivity.data.state])}
            </span>
          ) : null}
          <button type="button" className={BUTTON} disabled={sync.isPending || pending === 0} onClick={() => sync.mutate(undefined)}>
            {sync.isPending ? t("sync.working") : `${t("sync.now")}${pending > 0 ? ` (${pending})` : ""}`}
          </button>
        </div>
      </div>
      <p className="text-sm text-muted">{t("sync.help")}</p>
      {sync.isError ? <ProblemNotice error={sync.error} /> : null}
      {lastReport ? (
        <div role="status" className="rounded-md border border-border bg-surface p-3 text-sm">
          <p className="font-medium">{t("sync.lastRun")} {t(`sync.session.${lastReport.session}` as "sync.session.ONLINE")}</p>
          {lastReport.outcomes.length > 0 ? (
            <ul className="mt-1 list-disc pl-5">
              {lastReport.outcomes.map((o) => (
                <li key={o.operation_id}>
                  {o.operation_id.slice(0, 8)} · {o.outcome}{"detail" in o ? ` · ${o.detail}` : ""}{"code" in o ? ` · ${o.code}` : ""}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {local.isPending ? <p className="text-sm text-muted">{t("sync.loading")}</p> : null}
      {local.isError ? <ProblemNotice error={local.error} /> : null}
      {view && view.operations.length === 0 ? <p className="text-sm text-muted">{t("sync.empty")}</p> : null}
      {groups && view
        ? (Object.keys(groups) as (keyof typeof groups)[]).map((key) =>
            groups[key].length > 0 ? (
              <section key={key} className={CARD} aria-labelledby={`sync-${key}`}>
                <h2 id={`sync-${key}`} className="text-base font-semibold">{t(GROUP_LABEL[key])} ({groups[key].length})</h2>
                <ul className="mt-3 flex flex-col gap-3">
                  {groups[key].map((op) => (
                    <li key={op.operation_id}>
                      <OperationRow op={op} view={view} principalId={principalId} onSyncOne={() => sync.mutate(op.operation_id)} syncing={sync.isPending} onChanged={refresh} />
                    </li>
                  ))}
                </ul>
              </section>
            ) : null,
          )
        : null}
    </div>
  );
}

function OperationRow({ op, view, principalId, onSyncOne, syncing, onChanged }: { op: QueuedOperation; view: LocalView; principalId: string; onSyncOne: () => void; syncing: boolean; onChanged: () => Promise<void> }) {
  const pkg = view.packages.get(op.inspection_id);
  const receipt = view.receipts.get(op.operation_id);
  const conflict = view.conflicts.get(op.operation_id);
  const bytes = view.evidenceBytes.get(op.inspection_id) ?? 0;
  const reference = pkg?.package.case.public_reference ?? op.inspection_id.slice(0, 8);
  return (
    <div className="rounded-md border border-border p-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-medium">
            <Link to={`/inspections/${op.inspection_id}`} className="text-primary">{reference}</Link>
            {pkg ? ` · ${t("queue.attempt")} ${pkg.package.inspection.attempt_number}` : ""} · {op.operation_type === "SUBMIT_INSPECTION_REPORT" ? t("sync.type.report") : t("sync.type.failedVisit")}
          </p>
          <p className="text-muted">
            {t("sync.captured")} {new Date(op.created_at).toLocaleString()} · {t("sync.versions")} {t("sync.pkg")} v{op.base_inspection_version} / {t("sync.assignment")} v{op.assignment_version} · {t("sync.evidenceSize")} {(bytes / 1024).toFixed(0)} KB
          </p>
          {op.last_error ? <p className="text-warning">{op.last_error.code}: {op.last_error.detail} ({new Date(op.last_error.at).toLocaleTimeString()})</p> : null}
          {receipt ? (
            <p className="text-positive">
              {t("sync.receipt")} {receipt.receipt.accepted_entity_kind} {receipt.receipt.accepted_entity_id?.slice(0, 8)} · {receipt.receipt.accepted_at ? new Date(receipt.receipt.accepted_at).toLocaleString() : ""} · v{receipt.receipt.returned_inspection_version}
            </p>
          ) : null}
          {op.attempts > 0 ? <p className="text-xs text-muted">{t("sync.attempts")} {op.attempts}</p> : null}
        </div>
        <div className="flex flex-col items-end gap-2">
          <span className={`rounded-md px-2 py-0.5 text-xs ${op.state === "ACCEPTED" ? "bg-positive-soft text-positive" : op.state === "CONFLICT" ? "bg-danger-soft text-danger" : "bg-canvas text-ink"}`}>{t(STATE_LABEL[op.state])}</span>
          {op.state !== "ACCEPTED" && op.state !== "CONFLICT" ? (
            <button type="button" className={SECONDARY} disabled={syncing} onClick={onSyncOne}>{t("sync.thisOne")}</button>
          ) : null}
        </div>
      </div>
      {conflict && op.state === "CONFLICT" ? <ConflictPanel op={op} conflict={conflict} pkg={pkg} principalId={principalId} onChanged={onChanged} /> : null}
    </div>
  );
}

function ConflictPanel({ op, conflict, pkg, onChanged }: { op: QueuedOperation; conflict: StoredConflict; pkg: StoredPackage | undefined; principalId: string; onChanged: () => Promise<void> }) {
  const [summary, setSummary] = useState("");
  const [reason, setReason] = useState("");
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const ids = { summary: useId(), reason: useId() };
  const propose = useMutation({
    mutationFn: async () => {
      if (!op.manifest) throw new Error("no frozen manifest to propose");
      const result = await proposeConflict(op.inspection_id, {
        application_version: pkg?.package.versions.application_version ?? op.manifest.application_version,
        operation_id: op.operation_id,
        local_manifest: op.manifest,
        safe_local_summary: summary,
        reason,
      });
      await offlineDb().conflicts.put({ ...conflict, resolution: "PROPOSED" });
      return result;
    },
    onSuccess: onChanged,
  });
  const discard = useMutation({
    mutationFn: async () => {
      await offlineDb().conflicts.put({ ...conflict, resolution: "DISCARDED" });
      await updateOperation(op, { last_error: { code: "DISCARDED", detail: "Local proposal discarded by the officer", at: new Date().toISOString() } });
    },
    onSuccess: onChanged,
  });
  return (
    <div className="mt-3 grid gap-3 border-t border-border pt-3 sm:grid-cols-2">
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{t("sync.local")}</h3>
        <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          <dt className="text-muted">{t("sync.pkg")}</dt>
          <dd>v{op.base_inspection_version} · {t("sync.assignment")} v{op.assignment_version}</dd>
          <dt className="text-muted">{t("sync.manifest")}</dt>
          <dd>{op.manifest_sha256?.slice(0, 12) ?? "-"}</dd>
        </dl>
      </div>
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{t("sync.server")}</h3>
        <p className="mt-1 text-danger">{conflict.problem.code}: {conflict.problem.detail}</p>
        <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          {Object.entries(conflict.server).map(([k, v]) => (
            <Fragment key={k}>
              <dt className="text-muted">{k}</dt>
              <dd>{typeof v === "object" ? JSON.stringify(v) : String(v as string | number | boolean | null)}</dd>
            </Fragment>
          ))}
        </dl>
      </div>
      {conflict.resolution === null ? (
        <form className="flex flex-col gap-2 sm:col-span-2" onSubmit={(e) => e.preventDefault()}>
          <label htmlFor={ids.summary}>{t("sync.safeSummary")}</label>
          <textarea id={ids.summary} className={FIELD} rows={2} value={summary} onChange={(e) => setSummary(e.target.value)} minLength={10} />
          <label htmlFor={ids.reason}>{t("policy.reason")}</label>
          <textarea id={ids.reason} className={FIELD} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} minLength={10} />
          {propose.isError ? <ProblemNotice error={propose.error} /> : null}
          <div className="flex flex-wrap gap-3">
            <button type="button" className={BUTTON} disabled={summary.trim().length < 10 || reason.trim().length < 10 || propose.isPending || !op.manifest} onClick={() => propose.mutate()}>{t("sync.propose")}</button>
            {confirmDiscard ? (
              <button type="button" className={SECONDARY} disabled={discard.isPending} onClick={() => discard.mutate()}>{t("sync.confirmDiscard")}</button>
            ) : (
              <button type="button" className={SECONDARY} onClick={() => setConfirmDiscard(true)}>{t("sync.discard")}</button>
            )}
          </div>
          <p className="text-xs text-muted">{t("sync.conflictHelp")}</p>
        </form>
      ) : (
        <p className="text-sm text-muted sm:col-span-2">{conflict.resolution === "PROPOSED" ? t("sync.proposed") : t("sync.discarded")}</p>
      )}
    </div>
  );
}
