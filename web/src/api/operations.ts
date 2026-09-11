/** Operations (API-103..106, UI-20): jobs with sanitised metadata, a health summary and the two
 *  recovery commands (safe retry of the same logical action; reconcile before any retry). */

import { queryOptions } from "@tanstack/react-query";

import { ensureCsrf } from "./auth";
import { request } from "./client";

export interface Job {
  job_id: string;
  logical_action_id: string;
  kind: string;
  state: "PENDING" | "RUNNING" | "RETRY_WAIT" | "COMPLETE" | "DEAD_LETTER" | "RECONCILIATION_REQUIRED";
  attempt_count: number;
  max_attempts: number;
  next_attempt_at: string | null;
  lease_owner: string | null;
  lease_until: string | null;
  last_error_code: string | null;
  disposition: string | null;
  aggregate_ref: Record<string, string>;
  created_at: string;
  updated_at: string;
  next_permitted_action: "RETRY" | "RECONCILE" | null;
}

export interface OperationsSummary {
  as_of: string;
  outbox: { pending: number; dispatched_incomplete: number; oldest_pending_seconds: number };
  due_jobs: number;
  oldest_due_seconds: number;
  running: number;
  expired_leases: number;
  retry_wait: number;
  dead_letter: number;
  reconciliation_required: number;
  worker_last_activity_seconds: number | null;
  worker_heartbeat_ok: boolean;
  by_kind: Record<string, number>;
}

async function recovery(path: string, reason: string): Promise<Job & { procedure?: string }> {
  await ensureCsrf();
  const response = await request<{ data: Job & { procedure?: string } }>(path, { method: "POST", body: { reason }, idempotencyKey: crypto.randomUUID() });
  return response.data.data;
}

/** API-105. */
export function retryJob(jobId: string, reason: string) {
  return recovery(`/jobs/${jobId}/retry`, reason);
}

/** API-106. */
export function reconcileJob(jobId: string, reason: string) {
  return recovery(`/jobs/${jobId}/reconcile`, reason);
}

export function jobsQuery(states: string[] = []) {
  const search = new URLSearchParams();
  for (const s of states) search.append("state", s);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return queryOptions({
    queryKey: ["jobs", states.join(",")] as const,
    queryFn: async ({ signal }) => (await request<{ data: { summary: OperationsSummary; items: Job[] } }>(`/jobs${suffix}`, { signal })).data.data,
  });
}
