/**
 * Offline package, synchronisation and conflict endpoints (API-048..052). The manifest posted
 * to `/sync/operations` is frozen on the device; its `operation_id` doubles as the idempotency
 * key so a lost response replays the same receipt instead of creating a second report.
 */

import { queryOptions } from "@tanstack/react-query";

import { ensureCsrf } from "./auth";
import { request } from "./client";
import type { ChecklistItem, Inspection, Observation } from "./inspections";

export interface OfflinePackage {
  package_id: string;
  issued_at: string;
  expires_at: string;
  schema_version: string;
  supported_schema_versions: string[];
  principal_id: string;
  authz_epoch: number;
  inspection: Inspection;
  checklist_items: ChecklistItem[];
  versions: { application_version: number; inspection_version: number; assignment_version: number; checklist_version: string };
  case: { application_id: string; public_reference: string | null; status: string; premises_display_name: string; locality: string; category_key: string; owner_queue: string };
  failed_visit_reasons: string[];
  operations: string[];
  limits: { max_file_bytes: number; allowed_media_types: string[] };
  notice: string;
}

export async function fetchOfflinePackage(inspectionId: string): Promise<{ pkg: OfflinePackage; etag: string }> {
  const response = await request<{ data: OfflinePackage }>(`/inspections/${inspectionId}/offline-package`);
  return { pkg: response.data.data, etag: response.etag ?? "" };
}

export type OperationType = "SUBMIT_INSPECTION_REPORT" | "RECORD_FAILED_VISIT";

export interface ManifestEnvelope {
  operation_id: string;
  operation_type: OperationType;
  inspection_id: string;
  application_version: number;
  base_inspection_version: number;
  assignment_version: number;
  schema_version: "1.0";
  captured_at: string;
}

export interface ReportManifest extends ManifestEnvelope {
  operation_type: "SUBMIT_INSPECTION_REPORT";
  checklist_version: string;
  observations: Observation[];
  summary: string;
  declaration_accepted: true;
}

export interface FailedVisitManifest extends ManifestEnvelope {
  operation_type: "RECORD_FAILED_VISIT";
  reason_code: string;
  reason: string;
  document_version_ids?: string[];
}

export type SyncManifest = ReportManifest | FailedVisitManifest;

export interface SyncReceipt {
  operation_id: string;
  operation_type: OperationType;
  state: "ACCEPTED" | "CONFLICT";
  accepted_entity_kind?: "REPORT" | "VISIT_OUTCOME";
  accepted_entity_id?: string | null;
  accepted_at?: string;
  returned_application_version?: number | null;
  returned_inspection_version?: number | null;
  command_id?: string;
  sha256: string;
  replayed: boolean;
  problem?: { code: string; detail: string; violations?: { pointer: string; code: string; message: string }[] };
  server?: Record<string, unknown>;
}

/** API-049. `ifMatch` carries the package's inspection version; the key is the operation id. */
export async function postSyncOperation(manifest: SyncManifest, inspectionEtag: string): Promise<{ receipt: SyncReceipt; etag: string }> {
  await ensureCsrf();
  const response = await request<{ data: SyncReceipt }>("/sync/operations", {
    method: "POST",
    body: manifest,
    ifMatch: inspectionEtag,
    idempotencyKey: manifest.operation_id,
  });
  return { receipt: response.data.data, etag: response.etag ?? "" };
}

/** API-050: the canonical recorded outcome, or 404 when nothing was ever received. */
export async function fetchSyncReceipt(operationId: string): Promise<SyncReceipt> {
  return (await request<{ data: SyncReceipt }>(`/sync/operations/${operationId}`)).data.data;
}

export interface ReportConflict {
  conflict_id: string;
  inspection_id: string;
  operation_id: string;
  proposer: string;
  application_version_seen: number;
  safe_local_summary: string;
  reason: string;
  local_manifest_sha256: string;
  server_snapshot: Record<string, unknown>;
  state: "OPEN" | "RESOLVED";
  outcome: "PROPOSE_NEW_REPORT" | "REINSPECTION_REQUIRED" | "DECLINE" | null;
  resolution_reason: string | null;
  selected_evidence_ids: string[];
  resolved_by: string | null;
  resolved_at: string | null;
  created_at: string;
  version: number;
  etag?: string;
}

export async function proposeConflict(inspectionId: string, body: { application_version: number; operation_id: string; local_manifest: SyncManifest; safe_local_summary: string; reason: string }): Promise<ReportConflict> {
  await ensureCsrf();
  return (await request<{ data: ReportConflict }>(`/inspections/${inspectionId}/conflicts`, { method: "POST", body, idempotencyKey: `conflict:${body.operation_id}` })).data.data;
}

export const conflictsQuery = queryOptions({
  queryKey: ["conflicts"] as const,
  queryFn: async ({ signal }) => (await request<{ data: { items: ReportConflict[]; as_of: string } }>("/conflicts", { signal })).data.data,
});

export async function resolveConflict(conflict: ReportConflict, input: { outcome: "PROPOSE_NEW_REPORT" | "REINSPECTION_REQUIRED" | "DECLINE"; reason: string; selected_evidence_ids?: string[] }): Promise<ReportConflict> {
  await ensureCsrf();
  return (
    await request<{ data: ReportConflict }>(`/conflicts/${conflict.conflict_id}/resolve`, {
      method: "POST",
      body: { ...input },
      ifMatch: conflict.etag ?? `"conflict:${conflict.conflict_id}:v${conflict.version}"`,
      idempotencyKey: crypto.randomUUID(),
    })
  ).data.data;
}
