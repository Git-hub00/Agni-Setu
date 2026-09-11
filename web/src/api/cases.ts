/**
 * Submission (API-024), timeline (API-025), revisions (API-026), scrutiny start (API-027),
 * routing resolution (API-028) and the role overview (UI-09). Every command carries If-Match and
 * an idempotency key; a timed-out submission is retried with the SAME key so the server replays
 * the original receipt instead of creating a second one (UI spec s.7).
 */

import { queryOptions } from "@tanstack/react-query";

import { ensureCsrf } from "./auth";
import { request } from "./client";

export interface SubmissionReceipt {
  application_id: string;
  public_reference: string;
  draft_reference: string;
  status: string;
  accepted_at: string;
  submission_revision: number;
  submission_sha256: string;
  policy_version_id: string;
  policy_number: number;
  owner_queue: { queue_key: string; display_name: string; jurisdiction_code: string };
  routing: { resolved: boolean; exception_code: string | null; exception_id: string | null };
  obligations: { kind: string; state: string; time_basis: string; due_at: string | null; owner_queue: string }[];
  command_id: string;
  replayed: boolean;
  version: number;
}

export interface SubmissionInput {
  draft_revision: number;
  reviewed_policy_version_id: string;
  declaration_acceptances: { code: string; version: string; accepted: true }[];
  document_version_ids: string[];
}

export async function submitApplication(applicationId: string, body: SubmissionInput, etag: string, idempotencyKey: string) {
  await ensureCsrf();
  const response = await request<{ data: SubmissionReceipt }>(`/applications/${applicationId}/submit`, {
    method: "POST",
    body,
    ifMatch: etag,
    idempotencyKey,
  });
  return { receipt: response.data.data, etag: response.etag ?? "" };
}

export interface CaseEvent {
  event_id: string;
  event_type: string;
  aggregate_version: number;
  event_ordinal: number;
  occurred_at: string;
  actor_kind: string;
  audience: "PUBLIC_CASE" | "INTERNAL" | "RESTRICTED";
  payload: Record<string, unknown>;
}

export function timelineQuery(applicationId: string) {
  return queryOptions({
    queryKey: ["applications", "timeline", applicationId] as const,
    queryFn: async ({ signal }) =>
      (await request<{ data: { items: CaseEvent[]; next_cursor: string | null; has_more: boolean; as_of: string } }>(`/applications/${applicationId}/timeline`, { signal })).data.data,
  });
}

export async function startScrutiny(applicationId: string, reason: string, etag: string, idempotencyKey: string) {
  await ensureCsrf();
  const response = await request<{ data: { status: string } }>(`/applications/${applicationId}/start-scrutiny`, {
    method: "POST",
    body: { reason },
    ifMatch: etag,
    idempotencyKey,
  });
  return { status: response.data.data.status, etag: response.etag ?? "" };
}

export interface RoutingResolutionInput {
  target_jurisdiction_id: string;
  target_queue_id: string;
  routing_artifact_id: string;
  reason: string;
  exception_id: string;
}

export async function resolveRouting(applicationId: string, body: RoutingResolutionInput, etag: string, idempotencyKey: string) {
  await ensureCsrf();
  const response = await request<{ data: { owner_queue: { queue_key: string } } }>(`/applications/${applicationId}/resolve-routing`, {
    method: "POST",
    body,
    ifMatch: etag,
    idempotencyKey,
  });
  return { ownerQueue: response.data.data.owner_queue.queue_key, etag: response.etag ?? "" };
}

export interface Overview {
  as_of: string;
  role: "applicant" | "staff";
  counts: {
    drafts: number;
    open: number;
    action_required: number;
    review_waiting: number;
    received: number;
    by_status: Record<string, number>;
    due_soon?: number;
    overdue?: number;
    routing_exceptions?: number;
  };
  priority?: { application_id: string; public_reference: string | null; kind: string; due_at: string | null; owner_queue: string }[];
  latest_events: (CaseEvent & { application_id: string; public_reference: string | null })[];
}

export const overviewQuery = queryOptions({
  queryKey: ["overview"] as const,
  queryFn: async ({ signal }) => (await request<{ data: Overview }>("/overview", { signal })).data.data,
});
