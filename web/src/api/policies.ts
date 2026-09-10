/**
 * Policy governance endpoints API-095..102 (FR-27). Actions are hints from the server; every
 * command is revalidated there with the actor's current authority, the frozen candidate hash and
 * the version precondition (If-Match).
 */

import { queryOptions } from "@tanstack/react-query";

import { ensureCsrf } from "./auth";
import { request } from "./client";

export type PolicyState = "DRAFT" | "IN_REVIEW" | "RETURNED" | "APPROVED" | "SCHEDULED" | "ACTIVE" | "RETIRED";

export interface PolicySummary {
  policy_version_id: string;
  service_key: string;
  jurisdiction_code: string | null;
  number: number;
  state: PolicyState;
  payload_sha256: string;
  effective_from: string | null;
  effective_until: string | null;
  prepared_by: string;
  approved_by: string | null;
  version: number;
  updated_at: string;
}

export interface AllowedAction {
  key: "edit" | "submit-review" | "simulate" | "approve" | "return" | "activate";
  enabled: boolean;
  reason_code: string | null;
}

export interface PolicyDetail extends PolicySummary {
  payload: Record<string, unknown>;
  schema_version: string;
  review_candidate_sha256: string | null;
  approval_basis: string;
  returned_reason: string;
  source_references: string[];
  contributors: { principal_id: string; action: string; at: string }[];
  simulations: { simulation_id: string; candidate_sha256: string; suite: string; passed: boolean; completed_at: string }[];
  allowed_actions: AllowedAction[];
}

export const policiesQuery = queryOptions({
  queryKey: ["policies", "list"] as const,
  queryFn: async ({ signal }) =>
    (await request<{ data: { items: PolicySummary[] } }>("/policies", { signal })).data.data.items,
});

export function policyDetailQuery(policyId: string) {
  return queryOptions({
    queryKey: ["policies", "detail", policyId] as const,
    queryFn: async ({ signal }) => {
      const response = await request<{ data: PolicyDetail }>(`/policies/${policyId}`, { signal });
      return { policy: response.data.data, etag: response.etag };
    },
  });
}

export type PolicyCommand = "submit-review" | "simulate" | "approve" | "return" | "activate";

export interface PolicyCommandInput {
  policyId: string;
  command: PolicyCommand;
  etag: string;
  idempotencyKey: string;
  body: Record<string, unknown>;
}

export async function runPolicyCommand(input: PolicyCommandInput): Promise<void> {
  await ensureCsrf();
  await request(`/policies/${input.policyId}/${input.command}`, {
    method: "POST",
    body: input.body,
    ifMatch: input.etag,
    idempotencyKey: input.idempotencyKey,
  });
}
