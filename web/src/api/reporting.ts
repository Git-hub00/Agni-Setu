/**
 * Reporting and controlled exports (API-081..084; FR-25/26; UI-22). Metrics come from one
 * cutoff and reconcile with the lists the same reader sees; exports freeze scope and purpose,
 * are generated asynchronously and are fetched only through a short-lived reauthorised ticket.
 */

import { queryOptions } from "@tanstack/react-query";

import { ensureCsrf } from "./auth";
import { request } from "./client";

export interface MetricsFilters {
  service_id?: string;
  jurisdiction_id?: string;
  category_key?: string;
  submitted_from?: string;
  submitted_to?: string;
  as_of?: string;
}

export interface Metrics {
  as_of: string;
  definition_version: string;
  scope: { kind: string; jurisdiction_ids?: string[] };
  filters: MetricsFilters;
  population: number;
  metrics: {
    received: number;
    open: number;
    completed: number;
    rejected: number;
    withdrawn: number;
    published_certificates: number;
    overdue_obligations: number;
    resolution_hours: { sample_size: number; median: number | null; p90: number | null; insufficient_sample: boolean };
  };
  by_status: Record<string, number>;
  reconciled: boolean;
  exclusions: { drafts: number };
  definitions: Record<string, string>;
}

export type ExportKind = "CASES" | "CERTIFICATES" | "AUDIT" | "REPORT";
export type ExportState = "READY" | "RUNNING" | "COMPLETE" | "FAILED" | "EXPIRED";

export const FIELD_SETS: Record<ExportKind, string[]> = {
  CASES: ["case-summary"],
  CERTIFICATES: ["register"],
  AUDIT: ["audit-summary"],
  REPORT: ["metrics"],
};

export interface ExportJob {
  export_id: string;
  kind: ExportKind;
  field_set_key: string;
  fields: string[];
  purpose: string;
  filters: Record<string, unknown>;
  scope: Record<string, unknown>;
  population: number | null;
  as_of: string;
  definition_version: string;
  state: ExportState;
  row_count: number | null;
  expires_at: string;
  last_error_code: string | null;
  requester_id: string;
  created_at: string;
  updated_at: string;
  version: number;
  etag: string;
  scope_valid: boolean | null;
  allowed_actions: { key: string; enabled: boolean; reason_code: string | null }[];
}

function search(filters: MetricsFilters): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters as Record<string, string | undefined>)) {
    if (value) params.set(key, value);
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

export function metricsQuery(filters: MetricsFilters = {}) {
  return queryOptions({
    queryKey: ["reports", "summary", search(filters)] as const,
    queryFn: async ({ signal }) => (await request<{ data: Metrics }>(`/reports/summary${search(filters)}`, { signal })).data.data,
  });
}

export const exportsQuery = queryOptions({
  queryKey: ["exports", "list"] as const,
  queryFn: async ({ signal }) => (await request<{ data: { items: ExportJob[]; as_of: string } }>("/exports", { signal })).data.data,
});

export function exportQuery(exportId: string) {
  return queryOptions({
    queryKey: ["exports", "detail", exportId] as const,
    queryFn: async ({ signal }) => (await request<{ data: ExportJob }>(`/exports/${exportId}`, { signal })).data.data,
  });
}

export interface ExportRequestInput {
  kind: ExportKind;
  field_set_key: string;
  purpose: string;
  filters?: MetricsFilters;
  as_of?: string;
}

/** API-082. */
export async function createExport(input: ExportRequestInput): Promise<ExportJob> {
  await ensureCsrf();
  const response = await request<{ data: ExportJob }>("/exports", {
    method: "POST",
    body: { ...input, format: "CSV" },
    idempotencyKey: crypto.randomUUID(),
  });
  return response.data.data;
}

export interface ExportAccess {
  url: string;
  expires_in_seconds: number;
  media_type: string;
  sha256: string | null;
  row_count: number | null;
}

/** API-084: reauthorise and receive a short-lived, requester-bound artifact URL. */
export async function requestExportAccess(exportId: string, reason: string): Promise<ExportAccess> {
  await ensureCsrf();
  const response = await request<{ data: ExportAccess }>(`/exports/${exportId}/access`, { method: "POST", body: { reason } });
  return response.data.data;
}
