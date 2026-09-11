/**
 * Certificate register, artifact access and public verification (API-067/068/069/073;
 * FR-21/FR-22, UI-16/17/18). Public verification is never cached: every result carries the
 * server's checked-at time and is fetched fresh.
 */

import { queryOptions } from "@tanstack/react-query";

import { ensureCsrf } from "./auth";
import { request } from "./client";

export type EffectiveStatus = "ACTIVE" | "EXPIRED" | "SUSPENDED" | "REVOKED" | "SUPERSEDED";

export interface CertificateSummary {
  certificate_id: string;
  certificate_number: string;
  application_id: string;
  public_reference: string | null;
  premises: { display_name: string; locality: string; category_key: string };
  outcome_kind: "DEMO_CERTIFICATE" | "ISSUED_DEPARTMENT" | "REGISTERED_EXTERNAL";
  recorded_status: "ACTIVE" | "SUSPENDED" | "REVOKED" | "SUPERSEDED";
  effective_status: EffectiveStatus;
  issued_at: string;
  valid_until: string | null;
  issuer_label: string;
  is_demo: boolean;
  artifact_available: boolean;
  version: number;
  updated_at: string;
}

export interface PendingIssuance {
  issuance_request_id: string;
  application_id: string;
  public_reference: string | null;
  premises: { display_name: string; locality: string; category_key: string };
  certificate_number: string;
  state: "READY" | "PROCESSING" | "RECONCILIATION_REQUIRED" | "PUBLISHED" | "FAILED";
  attempts: number;
  last_error_code: string | null;
  dependency: string;
  updated_at: string;
  is_demo: boolean;
}

export interface CertificateDetail extends CertificateSummary {
  predecessor_id: string | null;
  successor_ids: string[];
  artifact: { sha256: string; size_bytes: number; media_type: string; mode: string; renderer: string; rendered_at: string } | null;
  issuance: {
    issuance_request_id: string;
    state: string;
    published_at: string | null;
    template: { key: string; version: number };
    provider_request_id?: string | null;
    signature_verification?: Record<string, unknown> | null;
    attempts?: number;
  } | null;
  status_history: { action: string; effective_at: string; public_reason: string }[];
  allowed_actions: { key: string; enabled: boolean; reason_code: string | null }[];
  demo_notice: string | null;
  issuer_reference: string;
  verification_url: string;
}

export interface CertificateRegister {
  items: CertificateSummary[];
  pending_issuance: PendingIssuance[];
  as_of: string;
  demo_notice: string | null;
}

export interface PublicVerification {
  certificate_number: string;
  effective_status: EffectiveStatus;
  premises_display_name: string;
  locality: string;
  issued_at: string;
  valid_until: string | null;
  issuer_label: string;
  source: string;
  checked_at: string;
  is_demo: boolean;
  notice?: string;
}

export function certificatesQuery(params: { effective_status?: string; q?: string } = {}) {
  const search = new URLSearchParams();
  if (params.effective_status) search.set("effective_status", params.effective_status);
  if (params.q) search.set("q", params.q);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return queryOptions({
    queryKey: ["certificates", "list", params.effective_status ?? "", params.q ?? ""] as const,
    queryFn: async ({ signal }) => (await request<{ data: CertificateRegister }>(`/certificates${suffix}`, { signal })).data.data,
  });
}

export function certificateQuery(certificateId: string) {
  return queryOptions({
    queryKey: ["certificates", "detail", certificateId] as const,
    queryFn: async ({ signal }) => {
      const response = await request<{ data: CertificateDetail }>(`/certificates/${certificateId}`, { signal });
      return { certificate: response.data.data, etag: response.etag ?? "" };
    },
  });
}

/** API-069: fresh reauthorised, audited ticket for the labelled artifact. */
export async function requestCertificateAccess(certificateId: string): Promise<{ url: string; mode: string; label: string; expires_in_seconds: number }> {
  await ensureCsrf();
  const response = await request<{ data: { url: string; mode: string; label: string; expires_in_seconds: number } }>(`/certificates/${certificateId}/access`, {
    method: "POST",
    body: {},
    idempotencyKey: crypto.randomUUID(),
  });
  return response.data.data;
}

/** API-073: anonymous, rate-limited, never cached by the client either. */
export function publicVerificationQuery(lookup: string) {
  return queryOptions({
    queryKey: ["public-verification", lookup] as const,
    queryFn: async ({ signal }) =>
      (await request<{ data: PublicVerification }>(`/public/certificates/${encodeURIComponent(lookup)}`, { signal })).data.data,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });
}
