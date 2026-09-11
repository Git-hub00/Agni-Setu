/**
 * Guarded decisions (API-064 readiness, API-065 record, API-066 list; FR-20, UI-14). The
 * readiness read is advisory: the server re-evaluates every guard when the command runs.
 */

import { queryOptions } from "@tanstack/react-query";

import { ensureCsrf } from "./auth";
import { request } from "./client";

export type DecisionKind = "APPROVE" | "REJECT";

export interface Blocker {
  code: string;
  message: string;
  refs: string[];
}

export interface DecisionReadiness {
  application_id: string;
  public_reference: string | null;
  status: string;
  version: number;
  evidence: {
    submission_revision_id: string | null;
    submission_number: number | null;
    submission_sha256: string | null;
    report_id: string | null;
    report_revision: number | null;
    report_sha256: string | null;
    report_eligible: boolean | null;
    policy_version_id: string;
    policy_number: number;
    open_mandatory_findings: string[];
    reinspection_outstanding: string[];
    open_notices: string[];
  };
  authority: {
    grant_id: string | null;
    scope: string | null;
    inspector_cannot_decide: boolean;
    inspected_this_case: boolean;
  };
  approve: { eligible: boolean; blockers: Blocker[] };
  reject: { eligible: boolean; blockers: Blocker[] };
  evaluated_at: string;
  notice: string;
}

export interface DecisionRecord {
  decision_id: string;
  decision_number: number;
  kind: DecisionKind;
  public_reason: string;
  accepted_at: string;
  submission_revision_id: string;
  report_id: string | null;
  policy_version_id: string;
  reason?: string;
  actor_id?: string;
  authority_grant_id?: string;
  sha256?: string;
}

export interface DecisionReceipt {
  decision_id: string;
  decision_number: number;
  kind: DecisionKind;
  application_id: string;
  public_reference: string | null;
  status: string;
  accepted_at: string;
  public_reason: string;
  authority_grant_id: string;
  evidence_sha256: string;
  issuance: { issuance_request_id: string; certificate_number: string; state: string } | null;
  command_id: string;
  replayed: boolean;
  version?: number;
}

export interface DecisionInput {
  kind: DecisionKind;
  submission_revision_id: string;
  report_id?: string;
  reason: string;
  public_reason: string;
  review_acknowledged: true;
}

export function readinessQuery(applicationId: string) {
  return queryOptions({
    queryKey: ["decisions", "readiness", applicationId] as const,
    queryFn: async ({ signal }) => {
      const response = await request<{ data: DecisionReadiness }>(`/applications/${applicationId}/decision-readiness`, { signal });
      return { readiness: response.data.data, etag: response.etag ?? "" };
    },
    staleTime: 0,
  });
}

export function decisionsQuery(applicationId: string) {
  return queryOptions({
    queryKey: ["decisions", "list", applicationId] as const,
    queryFn: async ({ signal }) =>
      (await request<{ data: { items: DecisionRecord[]; as_of: string } }>(`/applications/${applicationId}/decisions`, { signal })).data.data,
  });
}

/** API-065: one stable key per review attempt so a retry after a lost response replays. */
export async function recordDecision(applicationId: string, input: DecisionInput, etag: string, key: string): Promise<DecisionReceipt> {
  await ensureCsrf();
  const response = await request<{ data: DecisionReceipt }>(`/applications/${applicationId}/decisions`, {
    method: "POST",
    body: input,
    ifMatch: etag,
    idempotencyKey: key,
  });
  return response.data.data;
}
