/**
 * Case lifecycle commands (API-030 withdraw, API-031/032 holds, API-063 return for
 * clarification). Every call carries the case (or hold) ETag and a fresh command key.
 */

import { ensureCsrf } from "./auth";
import { request } from "./client";

export interface Hold {
  hold_id: string;
  application_id: string;
  kind: "ADMINISTRATIVE" | "COURT_ORDER";
  state: "ACTIVE" | "RELEASED";
  reason: string;
  basis_document_id: string | null;
  authorized_by: string;
  starts_at: string;
  requested_end_at: string | null;
  ends_at: string | null;
  affected_obligation_ids: string[];
  command_block_scope: string[];
  released_by: string | null;
  release_reason: string | null;
  version: number;
  etag: string;
}

async function command<T>(path: string, body: Record<string, unknown>, etag: string): Promise<{ data: T; etag: string }> {
  await ensureCsrf();
  const response = await request<{ data: T }>(path, { method: "POST", body, ifMatch: etag, idempotencyKey: crypto.randomUUID() });
  return { data: response.data.data, etag: response.etag ?? "" };
}

/** API-030 / TR-13. */
export function withdrawApplication(applicationId: string, reason: string, etag: string) {
  return command<{ status: string; from_status: string; disposition: Record<string, unknown> }>(`/applications/${applicationId}/withdraw`, { reason }, etag);
}

/** API-031. */
export function createHold(
  applicationId: string,
  input: { kind: "ADMINISTRATIVE" | "COURT_ORDER"; reason: string; affected_obligation_ids: string[]; command_block_scope: string[]; basis_document_id?: string },
  etag: string,
) {
  return command<Hold>(`/applications/${applicationId}/holds`, { ...input }, etag);
}

/** API-032. */
export function releaseHold(holdId: string, reason: string, etag: string) {
  return command<Hold>(`/holds/${holdId}/release`, { reason }, etag);
}

/** API-063 / TR-14 (baseline 2.0: a new physical attempt is required). */
export function returnForClarification(
  applicationId: string,
  input: { report_id: string; items_requiring_clarification: { code: string; text: string }[]; reason: string },
  etag: string,
) {
  return command<{ inspection_id: string; attempt_number: number; purpose: string }>(
    `/applications/${applicationId}/return-review`,
    { ...input, requires_new_visit: true },
    etag,
  );
}
