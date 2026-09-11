/**
 * Obligations and escalations (API-074..077, UI-15). Every count and urgency label comes from
 * the server's single `as_of` cutoff so the monitoring screen never disagrees with itself.
 */

import { queryOptions } from "@tanstack/react-query";

import { ensureCsrf } from "./auth";
import { request } from "./client";

export type Urgency = "OVERDUE" | "DUE_SOON" | "ON_TRACK" | "PAUSED" | "NO_ESTIMATE" | "CLOSED";

export interface Escalation {
  escalation_id: string;
  obligation_id: string;
  threshold_action_id: string | null;
  manual: boolean;
  level: number;
  owner_queue: string;
  state: "OPEN" | "ACKNOWLEDGED" | "RESOLVED";
  reason: string;
  requested_by: string | null;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  next_action: string | null;
  created_at: string;
  version: number;
}

export interface ObligationRow {
  obligation_id: string;
  application_id: string | null;
  public_reference: string | null;
  application_status: string | null;
  kind: string;
  state: "ACTIVE" | "PAUSED" | "SATISFIED" | "CANCELLED";
  urgency: Urgency;
  time_basis: "CALENDAR" | "WORKING";
  budget_minutes: number;
  started_at: string;
  due_at: string | null;
  owner_queue: string;
  responsible_principal: string | null;
  generation: number;
  open_escalations: Escalation[];
  etag: string;
  version: number;
}

export interface ObligationList {
  as_of: string;
  counts: { overdue: number; due_soon: number; paused: number; open_escalations: number };
  items: ObligationRow[];
}

export interface ObligationDetail extends ObligationRow {
  clock: {
    basis: string;
    started_at: string;
    budget_minutes: number;
    active_minutes: number;
    remaining_minutes: number;
    due_at: string | null;
    paused: boolean;
    due_estimate: string | null;
    calendar_ref: string | null;
    pauses: { starts_at: string; ends_at: string | null }[];
  };
  thresholds: { threshold_action_id: string; threshold_key: string; action_type: string; level: number; scheduled_for: string; executed_at: string | null; disposition: string | null; superseded_at: string | null }[];
  escalations: Escalation[];
  as_of: string;
}

export function obligationsQuery(params: { urgency?: string; state?: string[] } = {}) {
  const search = new URLSearchParams();
  if (params.urgency) search.set("urgency", params.urgency);
  for (const s of params.state ?? []) search.append("state", s);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return queryOptions({
    queryKey: ["obligations", "list", params.urgency ?? "", (params.state ?? []).join(",")] as const,
    queryFn: async ({ signal }) => (await request<{ data: ObligationList }>(`/obligations${suffix}`, { signal })).data.data,
  });
}

export function obligationQuery(obligationId: string) {
  return queryOptions({
    queryKey: ["obligations", "detail", obligationId] as const,
    queryFn: async ({ signal }) => (await request<{ data: ObligationDetail }>(`/obligations/${obligationId}`, { signal })).data.data,
  });
}

async function command<T>(path: string, body: Record<string, unknown>, etag: string): Promise<T> {
  await ensureCsrf();
  const response = await request<{ data: T }>(path, { method: "POST", body, ifMatch: etag, idempotencyKey: crypto.randomUUID() });
  return response.data.data;
}

/** API-076: reasoned manual intervention; recipients come from the duty roster. */
export function createEscalation(row: ObligationRow, input: { reason: string; requested_level: number; next_action: string }) {
  return command<Escalation & { obligation_state: string }>(`/obligations/${row.obligation_id}/escalations`, { ...input }, row.etag);
}

/** API-077: records intervention ownership; never resolves the obligation. */
export function acknowledgeEscalation(escalation: Escalation, input: { reason: string; next_action?: string }) {
  return command<Escalation & { obligation_state: string }>(
    `/escalations/${escalation.escalation_id}/acknowledge`,
    { ...input },
    `"escalation:${escalation.escalation_id}:v${escalation.version}"`,
  );
}
