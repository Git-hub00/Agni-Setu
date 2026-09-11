/**
 * Explicit foreground synchronisation (docs/09 s.5). Every dependency is injected so the
 * algorithm is unit-testable against an in-memory IndexedDB and stubbed API calls:
 *   1. live session for the same principal (refresh /me)            -> else SIGN_IN_NEEDED
 *   2. current inspection facts; expired package / changed assignment -> local CONFLICT, no post
 *   3. upload each blob under an INSPECTION_EVIDENCE reservation; wait for CLEAN
 *   4. freeze the manifest once (id + hash); later edits are a new operation
 *   5. POST /sync/operations with the package's inspection If-Match and the id as key
 *   6. store the receipt before marking ACCEPTED
 *   7. on a lost response query the receipt / replay the same manifest
 *   8. on a structured conflict stop retrying and keep the local data
 */

import type { DocumentVersion } from "../api/applications";
import type { Principal } from "../api/auth";
import { ApiError, NetworkError } from "../api/errors";
import type { Inspection } from "../api/inspections";
import type { SyncManifest, SyncReceipt } from "../api/offline";
import { offlineDb, type QueuedOperation, type StoredPackage } from "./database";
import { buildReportManifest, canonicalJson, packageExpired, sha256Hex, updateOperation } from "./queue";

export interface SyncDeps {
  fetchMe: () => Promise<Principal>;
  fetchInspection: (inspectionId: string) => Promise<{ inspection: Inspection; etag: string }>;
  uploadBlob: (inspectionId: string, itemCode: string, file: File) => Promise<DocumentVersion>;
  fetchDocument: (documentId: string) => Promise<DocumentVersion>;
  postOperation: (manifest: SyncManifest, inspectionEtag: string) => Promise<{ receipt: SyncReceipt; etag: string }>;
  fetchReceipt: (operationId: string) => Promise<SyncReceipt>;
  now: () => Date;
}

export type OperationOutcome =
  | { operation_id: string; outcome: "ACCEPTED"; receipt: SyncReceipt }
  | { operation_id: string; outcome: "WAITING_FOR_SCAN" | "RETRY_LATER" | "SKIPPED"; detail: string }
  | { operation_id: string; outcome: "CONFLICT"; code: string; detail: string };

export interface SyncReport {
  session: "ONLINE" | "SIGN_IN_NEEDED" | "OFFLINE" | "SERVER_UNAVAILABLE" | "WRONG_PRINCIPAL";
  outcomes: OperationOutcome[];
}

async function markConflict(op: QueuedOperation, code: string, detail: string, server: Record<string, unknown>, at: string): Promise<void> {
  const db = offlineDb();
  await updateOperation(op, { state: "CONFLICT", last_error: { code, detail, at } });
  await db.conflicts.put({
    operation_id: op.operation_id,
    principal_id: op.principal_id,
    problem: { code, detail },
    server,
    resolution: null,
    recorded_at: at,
  });
}

async function uploadPendingBlobs(op: QueuedOperation, deps: SyncDeps): Promise<"READY" | "WAITING_FOR_SCAN" | "REJECTED"> {
  const db = offlineDb();
  let pendingScan = false;
  for (const blobId of op.blob_ids) {
    const state = await db.upload_state.get(blobId);
    const evidence = await db.local_evidence.get(blobId);
    if (!evidence) {
      // Browser eviction: the bytes are gone; never pretend they were accepted (docs/09 s.9).
      await updateOperation(op, { last_error: { code: "LOCAL_EVIDENCE_MISSING", detail: `Local file ${blobId.slice(0, 8)} is no longer on this device`, at: deps.now().toISOString() } });
      return "REJECTED";
    }
    if (!state?.document_version_id) {
      const version = await deps.uploadBlob(op.inspection_id, evidence.item_code, new File([evidence.bytes], evidence.name, { type: evidence.media_type }));
      await db.upload_state.put({ blob_id: blobId, reservation_id: null, document_version_id: version.document_version_id, scan_state: version.scan_state, updated_at: deps.now().toISOString() });
      if (version.scan_state !== "CLEAN") pendingScan = true;
      continue;
    }
    if (state.scan_state !== "CLEAN") {
      const current = await deps.fetchDocument(state.document_version_id);
      await db.upload_state.put({ ...state, scan_state: current.scan_state, updated_at: deps.now().toISOString() });
      if (current.scan_state === "REJECTED") {
        await updateOperation(op, { last_error: { code: "EVIDENCE_REJECTED", detail: `${evidence.name} was rejected by the security scan; replace it`, at: deps.now().toISOString() } });
        return "REJECTED";
      }
      if (current.scan_state !== "CLEAN") pendingScan = true;
    }
  }
  return pendingScan ? "WAITING_FOR_SCAN" : "READY";
}

async function freezeManifest(op: QueuedOperation, stored: StoredPackage, deps: SyncDeps): Promise<QueuedOperation> {
  if (op.manifest) return op;
  const db = offlineDb();
  const draft = await db.report_drafts.get(op.inspection_id);
  if (!draft) throw new Error("local draft missing for queued report");
  const uploads = new Map<string, string>();
  for (const blobId of op.blob_ids) {
    const state = await db.upload_state.get(blobId);
    const evidence = await db.local_evidence.get(blobId);
    if (state?.document_version_id && evidence) uploads.set(`${evidence.item_code}:${blobId}`, state.document_version_id);
  }
  const observations = draft.observations.map((o) => ({
    item_code: o.item_code,
    result: o.result as "PASS" | "FAIL" | "NOT_VERIFIED" | "NOT_APPLICABLE",
    note: o.note,
    document_version_ids: [
      ...o.document_version_ids,
      ...draft.dirty_fields.filter((f) => f.startsWith(`${o.item_code}:`)).map((f) => uploads.get(f)).filter((v): v is string => typeof v === "string"),
    ],
  }));
  const manifest = buildReportManifest(op, stored, observations, draft.summary, draft.captured_at ?? deps.now().toISOString());
  return updateOperation(op, { manifest, manifest_sha256: await sha256Hex(canonicalJson(manifest)), state: "READY_TO_SUBMIT" });
}

export async function syncOperation(op: QueuedOperation, deps: SyncDeps): Promise<OperationOutcome> {
  const db = offlineDb();
  const at = deps.now().toISOString();
  if (op.state === "ACCEPTED" || op.state === "CONFLICT") return { operation_id: op.operation_id, outcome: "SKIPPED", detail: op.state };
  const stored = await db.packages.get(op.inspection_id);
  if (!stored) {
    await markConflict(op, "PACKAGE_MISSING", "The local package for this attempt is gone", {}, at);
    return { operation_id: op.operation_id, outcome: "CONFLICT", code: "PACKAGE_MISSING", detail: "local package missing" };
  }
  if (packageExpired(stored, deps.now())) {
    await markConflict(op, "OFFLINE_PACKAGE_EXPIRED", "The offline package expired; automatic acceptance stopped, local work kept", { expires_at: stored.expires_at }, at);
    return { operation_id: op.operation_id, outcome: "CONFLICT", code: "OFFLINE_PACKAGE_EXPIRED", detail: "package expired" };
  }
  // 2. current facts: assignment and attempt must still match the package.
  let current: { inspection: Inspection; etag: string };
  try {
    current = await deps.fetchInspection(op.inspection_id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      await markConflict(op, "ASSIGNMENT_CHANGED", "You are no longer assigned to this attempt; local submission is locked", {}, at);
      return { operation_id: op.operation_id, outcome: "CONFLICT", code: "ASSIGNMENT_CHANGED", detail: "not assigned" };
    }
    return { operation_id: op.operation_id, outcome: "RETRY_LATER", detail: error instanceof Error ? error.message : "inspection unavailable" };
  }
  const assignment = current.inspection.current_assignment;
  if (!assignment || assignment.version !== op.assignment_version) {
    await markConflict(op, "ASSIGNMENT_CHANGED", "The assignment changed since the package was downloaded", { assignment_version: assignment?.version ?? null }, at);
    return { operation_id: op.operation_id, outcome: "CONFLICT", code: "ASSIGNMENT_CHANGED", detail: "assignment version differs" };
  }
  if (current.inspection.version !== op.base_inspection_version) {
    // Not necessarily fatal (the server decides), but never silently rebase: keep the frozen
    // base version and let the server return the structured conflict.
    await updateOperation(op, { last_error: { code: "BASE_VERSION_STALE", detail: `server inspection version ${current.inspection.version} differs from package ${op.base_inspection_version}`, at } });
  }
  // 3. uploads
  if (op.state === "WAITING_FOR_UPLOAD" || op.state === "WAITING_FOR_SCAN" || op.state === "LOCAL_DRAFT") {
    let result: "READY" | "WAITING_FOR_SCAN" | "REJECTED";
    try {
      result = await uploadPendingBlobs(op, deps);
    } catch (error) {
      if (error instanceof NetworkError) return { operation_id: op.operation_id, outcome: "RETRY_LATER", detail: "network failed during upload" };
      throw error;
    }
    if (result === "WAITING_FOR_SCAN") {
      await updateOperation(op, { state: "WAITING_FOR_SCAN" });
      return { operation_id: op.operation_id, outcome: "WAITING_FOR_SCAN", detail: "evidence still in the security scan" };
    }
    if (result === "REJECTED") return { operation_id: op.operation_id, outcome: "RETRY_LATER", detail: "evidence rejected or missing; replace it" };
  }
  // 4. freeze
  const frozen = await freezeManifest({ ...op, state: "READY_TO_SUBMIT" }, stored, deps);
  if (!frozen.manifest) throw new Error("manifest not frozen");
  // 7. lost response first: an earlier attempt may already have been accepted.
  if (frozen.attempts > 0) {
    try {
      const known = await deps.fetchReceipt(frozen.operation_id);
      if (known.state === "ACCEPTED") {
        await db.receipts.put({ operation_id: frozen.operation_id, principal_id: frozen.principal_id, receipt: known, stored_at: at });
        await updateOperation(frozen, { state: "ACCEPTED" });
        return { operation_id: frozen.operation_id, outcome: "ACCEPTED", receipt: known };
      }
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 404)) {
        return { operation_id: frozen.operation_id, outcome: "RETRY_LATER", detail: "receipt lookup failed" };
      }
    }
  }
  // 5-6. submit with the frozen identity
  const submitting = await updateOperation(frozen, { state: "SUBMITTING", attempts: frozen.attempts + 1 });
  try {
    const { receipt } = await deps.postOperation(frozen.manifest, stored.inspection_etag);
    await db.receipts.put({ operation_id: frozen.operation_id, principal_id: frozen.principal_id, receipt, stored_at: deps.now().toISOString() });
    await updateOperation(submitting, { state: "ACCEPTED", last_error: null });
    return { operation_id: frozen.operation_id, outcome: "ACCEPTED", receipt };
  } catch (error) {
    if (error instanceof NetworkError) {
      await updateOperation(submitting, { state: "READY_TO_SUBMIT", last_error: { code: "NETWORK", detail: "The response was lost; the same manifest will be replayed", at } });
      return { operation_id: frozen.operation_id, outcome: "RETRY_LATER", detail: "network failed during submit" };
    }
    if (error instanceof ApiError) {
      if (error.status === 409 || error.status === 412 || error.status === 422 || error.status === 403) {
        const body = (error.body ?? {}) as { code?: string; detail?: string; server?: Record<string, unknown> };
        await markConflict(submitting, body.code ?? "CONFLICT", body.detail ?? error.message, body.server ?? {}, deps.now().toISOString());
        return { operation_id: frozen.operation_id, outcome: "CONFLICT", code: body.code ?? "CONFLICT", detail: body.detail ?? error.message };
      }
      if (error.status === 401) {
        await updateOperation(submitting, { state: "READY_TO_SUBMIT", last_error: { code: "SIGN_IN_NEEDED", detail: "Sign in again to continue", at } });
        return { operation_id: frozen.operation_id, outcome: "RETRY_LATER", detail: "sign-in needed" };
      }
      await updateOperation(submitting, { state: "READY_TO_SUBMIT", last_error: { code: `HTTP_${error.status}`, detail: error.message, at } });
      return { operation_id: frozen.operation_id, outcome: "RETRY_LATER", detail: error.message };
    }
    throw error;
  }
}

export async function syncAll(principalId: string, deps: SyncDeps, only?: string): Promise<SyncReport> {
  let me: Principal;
  try {
    me = await deps.fetchMe();
  } catch (error) {
    if (error instanceof NetworkError) return { session: "OFFLINE", outcomes: [] };
    if (error instanceof ApiError && error.status === 401) return { session: "SIGN_IN_NEEDED", outcomes: [] };
    return { session: "SERVER_UNAVAILABLE", outcomes: [] };
  }
  if (me.id !== principalId) return { session: "WRONG_PRINCIPAL", outcomes: [] };
  const ops = await offlineDb().operations.where("principal_id").equals(principalId).sortBy("created_at");
  const outcomes: OperationOutcome[] = [];
  for (const op of ops) {
    if (only && op.operation_id !== only) continue;
    if (op.state === "ACCEPTED" || op.state === "CONFLICT") continue;
    outcomes.push(await syncOperation(op, deps));
  }
  return { session: "ONLINE", outcomes };
}
