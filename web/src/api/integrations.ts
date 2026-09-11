/** Integrations and reconciliation (API-107..111; FR-29; UI-25). Configuration is sanitised
 *  server-side (secret references only); conflicts are resolved with evidence and the current
 *  version; a passing probe is never proof that a partner workflow is live. */

import { queryOptions } from "@tanstack/react-query";

import { ensureCsrf } from "./auth";
import { request } from "./client";

export type IntegrationMode = "SIMULATED" | "SANDBOX" | "LIVE";
export type IntegrationState = "DISABLED" | "ENABLED" | "DEGRADED";
export type HealthStatus = "NOT_RUN" | "OK" | "FAIL" | "UNKNOWN";

export interface Integration {
  integration_id: string;
  key: string;
  display_name: string;
  mode: IntegrationMode;
  provider_kind: string;
  state: IntegrationState;
  capabilities: string[];
  system_of_record_fields: string[];
  endpoint_allowlist: string[];
  credential_secret_ref: string | null;
  credential_configured: boolean;
  owner_queue: string | null;
  freshness: "FRESH" | "STALE" | "UNKNOWN";
  freshness_budget_seconds: number;
  last_event_at: string | null;
  last_health_status: HealthStatus;
  last_health_at: string | null;
  last_health_detail: string;
  allowed_tests: string[];
  open_conflicts: number;
  inbox_counts: Record<string, number>;
  notice: string;
  version: number;
  etag: string;
}

export interface InboxRow {
  receipt_id: string;
  source_event_id: string;
  source_entity_id: string;
  source_sequence: number | null;
  event_type: string;
  schema_version: string;
  occurred_at: string;
  received_at: string;
  state: "RECEIVED" | "PROCESSED" | "QUARANTINED" | "CONFLICT";
  disposition: string | null;
  error_code: string | null;
  payload_sha256_prefix: string;
  auth_scheme: string | null;
}

export interface EntityState {
  source_entity_id: string;
  applied_sequence: number | null;
  applied_source_version: string | null;
  applied_event_id: string | null;
  applied_occurred_at: string | null;
  snapshot: Record<string, unknown>;
  application_id: string | null;
  updated_at: string;
}

export interface IntegrationDetail extends Integration {
  recent_inbox: InboxRow[];
  entity_states: EntityState[];
}

export type ResolutionOutcome = "APPLY_VERIFIED_SOURCE" | "IGNORE_DUPLICATE" | "REQUEST_RESEND" | "KEEP_QUARANTINED";

export interface IntegrationConflict {
  conflict_id: string;
  integration_id: string;
  integration_key: string;
  source_entity_id: string;
  reason_code: string;
  detail: Record<string, unknown>;
  owner_queue: string | null;
  state: "OPEN" | "RESOLVED";
  outcome: string | null;
  resolution_basis: Record<string, unknown> | null;
  resolved_by_id: string | null;
  resolved_at: string | null;
  inbox: InboxRow | null;
  created_at: string;
  updated_at: string;
  version: number;
  etag: string;
  allowed_outcomes: ResolutionOutcome[];
}

export const integrationsQuery = queryOptions({
  queryKey: ["integrations", "list"] as const,
  queryFn: async ({ signal }) => (await request<{ data: { items: Integration[]; as_of: string } }>("/integrations", { signal })).data.data,
});

export function integrationQuery(ref: string | null) {
  return queryOptions({
    queryKey: ["integrations", "detail", ref ?? ""] as const,
    enabled: ref !== null,
    queryFn: async ({ signal }) => (await request<{ data: IntegrationDetail }>(`/integrations/${ref ?? ""}`, { signal })).data.data,
  });
}

export function conflictsQuery(state?: "OPEN" | "RESOLVED") {
  const suffix = state ? `?state=${state}` : "";
  return queryOptions({
    queryKey: ["integrations", "conflicts", state ?? ""] as const,
    queryFn: async ({ signal }) => (await request<{ data: { items: IntegrationConflict[]; as_of: string; scope: string } }>(`/integration-conflicts${suffix}`, { signal })).data.data,
  });
}

async function command<T>(path: string, body: Record<string, unknown>, etag: string): Promise<T> {
  await ensureCsrf();
  const response = await request<{ data: T }>(path, { method: "POST", body, ifMatch: etag, idempotencyKey: crypto.randomUUID() });
  return response.data.data;
}

/** API-108. */
export function testIntegration(ref: string, input: { test_case_key: string; reason: string }, etag: string) {
  return command<{ job_id: string; state: string; notice: string }>(`/integrations/${ref}/test`, { ...input }, etag);
}

export interface ResolutionInput {
  outcome: ResolutionOutcome;
  reason: string;
  authoritative_source_version?: string;
  verification_evidence_refs: string[];
}

/** API-111. */
export function resolveConflict(conflictId: string, input: ResolutionInput, etag: string) {
  return command<IntegrationConflict & { applied_sequence: number | null }>(`/integration-conflicts/${conflictId}/resolve`, { ...input }, etag);
}
