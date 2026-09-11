/** Audit reader (API-085/086; FR-28; UI-23). Scoped, redacted where the role requires it, and
 *  every listing is itself audited server-side. */

import { queryOptions } from "@tanstack/react-query";

import { request } from "./client";

export interface AuditFilters {
  entity_type?: string;
  entity_id?: string;
  action?: string;
  actor_id?: string;
  request_id?: string;
  from?: string;
  to?: string;
  limit?: string;
}

export interface AuditEvent {
  audit_event_id: string;
  entity_type: string;
  entity_id: string;
  action: string;
  actor_id: string | null;
  authority_grant_id: string | null;
  request_id: string;
  timestamp: string;
  summary: Record<string, unknown>;
  redacted: boolean;
  hash: string;
  prior_hash: string | null;
  checkpoint_batch_id: string | null;
}

export interface AuditList {
  items: AuditEvent[];
  has_more: boolean;
  redacted: boolean;
  as_of: string;
  notice: string;
}

export interface AuditDetail extends AuditEvent {
  integrity: { chain_valid: boolean; checked_at: string; label: string };
}

function search(filters: AuditFilters): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters as Record<string, string | undefined>)) {
    if (value) params.set(key, value);
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

export function auditEventsQuery(filters: AuditFilters = {}) {
  return queryOptions({
    queryKey: ["audit", "list", search(filters)] as const,
    queryFn: async ({ signal }) => (await request<{ data: AuditList }>(`/audit-events${search(filters)}`, { signal })).data.data,
  });
}

export function auditEventQuery(auditEventId: string | null) {
  return queryOptions({
    queryKey: ["audit", "detail", auditEventId ?? ""] as const,
    enabled: auditEventId !== null,
    queryFn: async ({ signal }) => (await request<{ data: AuditDetail }>(`/audit-events/${auditEventId ?? ""}`, { signal })).data.data,
  });
}
