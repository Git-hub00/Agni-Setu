/**
 * Local operation queue (docs/09 s.3-4). Everything here is "saved on this device": a queued
 * operation is durable local intent with an immutable identity; only a stored server receipt
 * makes it "Submitted and received". Manifests are frozen once and never edited behind an id.
 */

import type { ObservationResult } from "../api/inspections";
import type { FailedVisitManifest, OfflinePackage, ReportManifest, SyncManifest } from "../api/offline";
import { ensureDeviceMeta, offlineDb, type LocalEvidence, type OperationState, type QueuedOperation, type ReportDraftRecord, type StoredPackage } from "./database";

export const PACKAGE_TTL_MS = 24 * 60 * 60 * 1000;

/** Deterministic JSON (sorted keys) so the same content always hashes the same way. */
export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map((v) => canonicalJson(v)).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${canonicalJson(v)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export async function sha256Hex(input: string | ArrayBuffer): Promise<string> {
  const bytes = typeof input === "string" ? new TextEncoder().encode(input) : new Uint8Array(input);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function savePackage(pkg: OfflinePackage, inspectionEtag: string, principalId: string): Promise<StoredPackage> {
  // A different signed-in principal on this device purges the previous one's local data first.
  await ensureDeviceMeta(principalId, pkg.authz_epoch);
  const stored: StoredPackage = {
    inspection_id: pkg.inspection.inspection_id,
    principal_id: principalId,
    package: pkg,
    inspection_etag: inspectionEtag,
    downloaded_at: new Date().toISOString(),
    expires_at: pkg.expires_at,
  };
  await offlineDb().packages.put(stored);
  return stored;
}

export function getPackage(inspectionId: string): Promise<StoredPackage | undefined> {
  return offlineDb().packages.get(inspectionId);
}

export function packageExpired(pkg: StoredPackage, now: Date = new Date()): boolean {
  return new Date(pkg.expires_at).getTime() <= now.getTime();
}

export async function saveLocalDraft(draft: Omit<ReportDraftRecord, "saved_at" | "local_revision">): Promise<ReportDraftRecord> {
  const db = offlineDb();
  const existing = await db.report_drafts.get(draft.inspection_id);
  const record: ReportDraftRecord = {
    ...draft,
    local_revision: (existing?.local_revision ?? 0) + 1,
    saved_at: new Date().toISOString(),
  };
  await db.report_drafts.put(record);
  return record;
}

export function getLocalDraft(inspectionId: string): Promise<ReportDraftRecord | undefined> {
  return offlineDb().report_drafts.get(inspectionId);
}

export async function addLocalEvidence(input: { inspection_id: string; item_code: string; principal_id: string; file: Blob; name: string; media_type: string }): Promise<LocalEvidence> {
  const bytes = await input.file.arrayBuffer();
  const evidence: LocalEvidence = {
    blob_id: crypto.randomUUID(),
    inspection_id: input.inspection_id,
    item_code: input.item_code,
    principal_id: input.principal_id,
    name: input.name,
    media_type: input.media_type,
    size: input.file.size,
    sha256: await sha256Hex(bytes),
    bytes: input.file,
    captured_at: new Date().toISOString(),
  };
  const db = offlineDb();
  await db.local_evidence.put(evidence);
  await db.upload_state.put({ blob_id: evidence.blob_id, reservation_id: null, document_version_id: null, scan_state: null, updated_at: evidence.captured_at });
  return evidence;
}

export function listEvidence(inspectionId: string): Promise<LocalEvidence[]> {
  return offlineDb().local_evidence.where("inspection_id").equals(inspectionId).toArray();
}

export interface ReportOperationInput {
  principal_id: string;
  package: StoredPackage;
  observations: { item_code: string; result: ObservationResult; note: string; blob_ids: string[]; document_version_ids: string[] }[];
  summary: string;
  captured_at: string;
}

/** Queue a report captured offline. Uploads (if any) run at sync time; the manifest is frozen
 *  only when every referenced file has a CLEAN server reference (docs/09 s.5 step 3-4). */
export async function queueReportOperation(input: ReportOperationInput): Promise<QueuedOperation> {
  const now = new Date().toISOString();
  const blobIds = input.observations.flatMap((o) => o.blob_ids);
  const pkg = input.package.package;
  const op: QueuedOperation = {
    operation_id: crypto.randomUUID(),
    principal_id: input.principal_id,
    inspection_id: pkg.inspection.inspection_id,
    operation_type: "SUBMIT_INSPECTION_REPORT",
    manifest: null,
    manifest_sha256: null,
    base_inspection_version: pkg.versions.inspection_version,
    assignment_version: pkg.versions.assignment_version,
    inspection_etag: input.package.inspection_etag,
    blob_ids: blobIds,
    state: blobIds.length > 0 ? "WAITING_FOR_UPLOAD" : "READY_TO_SUBMIT",
    attempts: 0,
    last_error: null,
    created_at: now,
    updated_at: now,
  };
  // The pre-manifest draft is kept in the draft store so a later freeze can read it.
  await offlineDb().report_drafts.put({
    inspection_id: op.inspection_id,
    local_revision: 0,
    principal_id: input.principal_id,
    observations: input.observations.map((o) => ({ item_code: o.item_code, result: o.result, note: o.note, document_version_ids: o.document_version_ids })),
    summary: input.summary,
    dirty_fields: input.observations.flatMap((o) => o.blob_ids.map((b) => `${o.item_code}:${b}`)),
    captured_at: input.captured_at,
    saved_at: now,
  });
  if (blobIds.length === 0) {
    op.manifest = buildReportManifest(op, input.package, input.observations.map((o) => ({ item_code: o.item_code, result: o.result, note: o.note, document_version_ids: o.document_version_ids })), input.summary, input.captured_at);
    op.manifest_sha256 = await sha256Hex(canonicalJson(op.manifest));
  }
  await offlineDb().operations.put(op);
  return op;
}

export function buildReportManifest(
  op: QueuedOperation,
  stored: StoredPackage,
  observations: ReportManifest["observations"],
  summary: string,
  capturedAt: string,
): ReportManifest {
  const pkg = stored.package;
  return {
    operation_id: op.operation_id,
    operation_type: "SUBMIT_INSPECTION_REPORT",
    inspection_id: op.inspection_id,
    application_version: pkg.versions.application_version,
    base_inspection_version: pkg.versions.inspection_version,
    assignment_version: pkg.versions.assignment_version,
    schema_version: "1.0",
    captured_at: capturedAt,
    checklist_version: pkg.versions.checklist_version,
    observations,
    summary,
    declaration_accepted: true,
  };
}

export async function queueFailedVisitOperation(input: { principal_id: string; package: StoredPackage; reason_code: string; reason: string; captured_at: string }): Promise<QueuedOperation> {
  const now = new Date().toISOString();
  const pkg = input.package.package;
  const operationId = crypto.randomUUID();
  const manifest: FailedVisitManifest = {
    operation_id: operationId,
    operation_type: "RECORD_FAILED_VISIT",
    inspection_id: pkg.inspection.inspection_id,
    application_version: pkg.versions.application_version,
    base_inspection_version: pkg.versions.inspection_version,
    assignment_version: pkg.versions.assignment_version,
    schema_version: "1.0",
    captured_at: input.captured_at,
    reason_code: input.reason_code,
    reason: input.reason,
  };
  const op: QueuedOperation = {
    operation_id: operationId,
    principal_id: input.principal_id,
    inspection_id: manifest.inspection_id,
    operation_type: "RECORD_FAILED_VISIT",
    manifest,
    manifest_sha256: await sha256Hex(canonicalJson(manifest)),
    base_inspection_version: pkg.versions.inspection_version,
    assignment_version: pkg.versions.assignment_version,
    inspection_etag: input.package.inspection_etag,
    blob_ids: [],
    state: "READY_TO_SUBMIT",
    attempts: 0,
    last_error: null,
    created_at: now,
    updated_at: now,
  };
  await offlineDb().operations.put(op);
  return op;
}

export function listOperations(principalId: string): Promise<QueuedOperation[]> {
  return offlineDb().operations.where("principal_id").equals(principalId).sortBy("created_at");
}

export async function updateOperation(op: QueuedOperation, patch: Partial<QueuedOperation>): Promise<QueuedOperation> {
  const next: QueuedOperation = { ...op, ...patch, updated_at: new Date().toISOString() };
  await offlineDb().operations.put(next);
  return next;
}

export function groupByState(ops: QueuedOperation[]): Record<"NOT_UPLOADED" | "WAITING_FOR_SCAN" | "READY" | "CONFLICT" | "ACCEPTED", QueuedOperation[]> {
  const groups: Record<"NOT_UPLOADED" | "WAITING_FOR_SCAN" | "READY" | "CONFLICT" | "ACCEPTED", QueuedOperation[]> = {
    NOT_UPLOADED: [],
    WAITING_FOR_SCAN: [],
    READY: [],
    CONFLICT: [],
    ACCEPTED: [],
  };
  const bucket: Record<OperationState, keyof typeof groups> = {
    LOCAL_DRAFT: "NOT_UPLOADED",
    WAITING_FOR_UPLOAD: "NOT_UPLOADED",
    WAITING_FOR_SCAN: "WAITING_FOR_SCAN",
    READY_TO_SUBMIT: "READY",
    SUBMITTING: "READY",
    ACCEPTED: "ACCEPTED",
    CONFLICT: "CONFLICT",
  };
  for (const op of ops) groups[bucket[op.state]].push(op);
  return groups;
}

export type { SyncManifest };
