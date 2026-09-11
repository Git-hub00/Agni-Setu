/** Staff roster and authority governance (API-087..093; FR-02; UI-21). Every write is a kernel
 *  command with a reason and the current version; approval is always a different actor. */

import { queryOptions } from "@tanstack/react-query";

import { ensureCsrf } from "./auth";
import { request } from "./client";

export type GrantState = "PROPOSED" | "APPROVED" | "REVOKED" | "EXPIRED";
export const CAPABILITIES = [
  "case.decide",
  "certificate.status",
  "policy.approve",
  "policy.activate",
  "grant.approve",
  "staff.provision",
  "export.sensitive",
  "notice.publish",
] as const;
export type CapabilityKey = (typeof CAPABILITIES)[number];

export interface Grant {
  grant_id: string;
  subject_id: string;
  subject_display_name?: string;
  capability: string;
  scope_kind: "GLOBAL" | "JURISDICTION" | "SERVICE";
  jurisdiction_id: string | null;
  service_id: string | null;
  state: GrantState;
  effective_from: string;
  effective_until: string | null;
  preparer_id: string;
  approver_id: string | null;
  approved_at: string | null;
  revoked_at: string | null;
  version: number;
  etag: string;
}

export interface StaffRole {
  binding_id: string;
  role_key: string;
  jurisdiction_id: string | null;
  jurisdiction_code: string | null;
  service_id: string | null;
  effective_from: string;
  effective_until: string | null;
  revoked_at: string | null;
  in_force: boolean;
}

export interface StaffMember {
  principal_id: string;
  display_name: string;
  active: boolean;
  disabled_at: string | null;
  identity_bound: boolean;
  roles: StaffRole[];
  grants: Grant[];
  workload: { active_assignments: number };
  version: number;
  etag: string;
}

export interface StaffList {
  items: StaffMember[];
  scope: "GLOBAL" | "JURISDICTIONS";
  as_of: string;
  can_manage: boolean;
}

export const staffQuery = queryOptions({
  queryKey: ["staff", "list"] as const,
  queryFn: async ({ signal }) => (await request<{ data: StaffList }>("/staff", { signal })).data.data,
});

export const grantsQuery = queryOptions({
  queryKey: ["staff", "grants"] as const,
  queryFn: async ({ signal }) => (await request<{ data: { items: Grant[]; as_of: string } }>("/authority-grants", { signal })).data.data,
});

async function command<T>(path: string, body: Record<string, unknown>, etag?: string): Promise<T> {
  await ensureCsrf();
  const response = await request<{ data: T }>(path, { method: "POST", body, ...(etag ? { ifMatch: etag } : {}), idempotencyKey: crypto.randomUUID() });
  return response.data.data;
}

export interface GrantProposalInput {
  subject_id: string;
  capability: CapabilityKey;
  scope_kind: "GLOBAL" | "JURISDICTION" | "SERVICE";
  jurisdiction_id?: string;
  service_id?: string;
  effective_until?: string;
  reason: string;
}

/** API-091. */
export function proposeGrant(input: GrantProposalInput) {
  return command<{ grant_id: string; state: GrantState }>("/authority-grants", { ...input });
}

/** API-092. */
export function approveGrant(grantId: string, reason: string, etag: string) {
  return command<{ grant_id: string; state: GrantState }>(`/authority-grants/${grantId}/approve`, { reason }, etag);
}

/** API-093. */
export function revokeGrant(grantId: string, reason: string, etag: string) {
  return command<{ grant_id: string; state: GrantState }>(`/authority-grants/${grantId}/revoke`, { reason }, etag);
}

/** API-089. */
export function deactivateStaff(principalId: string, reason: string, etag: string) {
  return command<{ principal_id: string; active: boolean }>(`/staff/${principalId}/deactivate`, { reason }, etag);
}

/** API-090. */
export function reactivateStaff(principalId: string, accessRequestId: string, reason: string, etag: string) {
  return command<{ principal_id: string; active: boolean; role_key: string }>(`/staff/${principalId}/reactivate`, { access_request_id: accessRequestId, reason }, etag);
}
