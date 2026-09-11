/**
 * Local IndexedDB stores (docs/09 s.3) through Dexie with explicit versioned migrations. The
 * database is scoped to the installation; identity scoping is enforced by `device_meta` and the
 * queue (a different principal never sees another's cache). Nothing in here is a server record.
 */

import Dexie, { type EntityTable } from "dexie";

import type { OfflinePackage, SyncManifest, SyncReceipt } from "../api/offline";

export type OperationState =
  | "LOCAL_DRAFT"
  | "WAITING_FOR_UPLOAD"
  | "WAITING_FOR_SCAN"
  | "READY_TO_SUBMIT"
  | "SUBMITTING"
  | "ACCEPTED"
  | "CONFLICT";

export interface DeviceMeta {
  key: "device";
  installation_id: string;
  schema_version: number;
  principal_id: string | null;
  authz_epoch: number | null;
  updated_at: string;
}

export interface StoredPackage {
  inspection_id: string;
  principal_id: string;
  package: OfflinePackage;
  inspection_etag: string;
  downloaded_at: string;
  expires_at: string;
}

export interface ReportDraftRecord {
  inspection_id: string;
  local_revision: number;
  principal_id: string;
  observations: { item_code: string; result: string; note: string; document_version_ids: string[] }[];
  summary: string;
  dirty_fields: string[];
  captured_at: string | null;
  saved_at: string;
}

export interface LocalEvidence {
  blob_id: string;
  inspection_id: string;
  item_code: string;
  principal_id: string;
  name: string;
  media_type: string;
  size: number;
  sha256: string;
  bytes: Blob;
  captured_at: string;
}

export interface UploadState {
  blob_id: string;
  reservation_id: string | null;
  document_version_id: string | null;
  scan_state: "QUARANTINED" | "CLEAN" | "REJECTED" | null;
  updated_at: string;
}

export interface QueuedOperation {
  operation_id: string;
  principal_id: string;
  inspection_id: string;
  operation_type: SyncManifest["operation_type"];
  manifest: SyncManifest | null; // frozen once READY_TO_SUBMIT
  manifest_sha256: string | null;
  base_inspection_version: number;
  assignment_version: number;
  inspection_etag: string;
  blob_ids: string[];
  state: OperationState;
  attempts: number;
  last_error: { code: string; detail: string; at: string } | null;
  created_at: string;
  updated_at: string;
}

export interface StoredReceipt {
  operation_id: string;
  principal_id: string;
  receipt: SyncReceipt;
  stored_at: string;
}

export interface StoredConflict {
  operation_id: string;
  principal_id: string;
  problem: NonNullable<SyncReceipt["problem"]>;
  server: Record<string, unknown>;
  resolution: "PROPOSED" | "DISCARDED" | null;
  recorded_at: string;
}

export class AgniOfflineDatabase extends Dexie {
  device_meta!: EntityTable<DeviceMeta, "key">;
  packages!: EntityTable<StoredPackage, "inspection_id">;
  report_drafts!: EntityTable<ReportDraftRecord, "inspection_id">;
  local_evidence!: EntityTable<LocalEvidence, "blob_id">;
  upload_state!: EntityTable<UploadState, "blob_id">;
  operations!: EntityTable<QueuedOperation, "operation_id">;
  receipts!: EntityTable<StoredReceipt, "operation_id">;
  conflicts!: EntityTable<StoredConflict, "operation_id">;

  constructor(name = "agni-setu-offline") {
    super(name);
    // Version 1 (B11). Later schema changes add `this.version(n).stores(...).upgrade(...)`;
    // an upgrade must never clear stores that still hold unsent drafts or blobs.
    this.version(1).stores({
      device_meta: "key",
      packages: "inspection_id, principal_id, expires_at",
      report_drafts: "inspection_id, principal_id",
      local_evidence: "blob_id, inspection_id, principal_id",
      upload_state: "blob_id",
      operations: "operation_id, inspection_id, principal_id, state",
      receipts: "operation_id, principal_id",
      conflicts: "operation_id, principal_id",
    });
  }
}

export const SCHEMA_VERSION = 1;

let instance: AgniOfflineDatabase | null = null;

export function offlineDb(): AgniOfflineDatabase {
  instance ??= new AgniOfflineDatabase();
  return instance;
}

/** Test hook: swap the singleton (e.g. an in-memory IndexedDB). */
export function useOfflineDatabase(db: AgniOfflineDatabase | null): void {
  instance = db;
}

export async function ensureDeviceMeta(principalId: string | null, authzEpoch: number | null): Promise<DeviceMeta> {
  const db = offlineDb();
  const existing = await db.device_meta.get("device");
  const now = new Date().toISOString();
  if (!existing) {
    const created: DeviceMeta = {
      key: "device",
      installation_id: crypto.randomUUID(),
      schema_version: SCHEMA_VERSION,
      principal_id: principalId,
      authz_epoch: authzEpoch,
      updated_at: now,
    };
    await db.device_meta.put(created);
    return created;
  }
  if (principalId !== null && existing.principal_id !== null && existing.principal_id !== principalId) {
    // Identity switched: the previous principal's cache must never be exposed (docs/09 s.9).
    await purgeForPrincipal(existing.principal_id);
  }
  const updated: DeviceMeta = { ...existing, principal_id: principalId ?? existing.principal_id, authz_epoch: authzEpoch ?? existing.authz_epoch, updated_at: now };
  await db.device_meta.put(updated);
  return updated;
}

export async function purgeForPrincipal(principalId: string): Promise<void> {
  const db = offlineDb();
  await db.transaction("rw", [db.packages, db.report_drafts, db.local_evidence, db.upload_state, db.operations, db.receipts, db.conflicts], async () => {
    const blobs = await db.local_evidence.where("principal_id").equals(principalId).primaryKeys();
    await db.upload_state.bulkDelete(blobs);
    await db.local_evidence.where("principal_id").equals(principalId).delete();
    await db.packages.where("principal_id").equals(principalId).delete();
    await db.report_drafts.where("principal_id").equals(principalId).delete();
    await db.operations.where("principal_id").equals(principalId).delete();
    await db.receipts.where("principal_id").equals(principalId).delete();
    await db.conflicts.where("principal_id").equals(principalId).delete();
  });
}

/** Unsent work summary for logout / identity-switch warnings (docs/09 s.9). */
export async function unsentWork(principalId: string): Promise<{ drafts: number; operations: number; files: number }> {
  const db = offlineDb();
  const operations = await db.operations.where("principal_id").equals(principalId).filter((o) => o.state !== "ACCEPTED").count();
  const drafts = await db.report_drafts.where("principal_id").equals(principalId).count();
  const files = await db.local_evidence.where("principal_id").equals(principalId).count();
  return { drafts, operations, files };
}
