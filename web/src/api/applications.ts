/**
 * Application endpoints API-020..023 (FR-04/FR-09) and document endpoints API-033..037 (FR-05).
 * Drafts are server state: every save carries the edited draft revision, the application ETag
 * (If-Match) and an idempotency key so a retried save replays instead of duplicating.
 */

import { queryOptions } from "@tanstack/react-query";

import { ensureCsrf } from "./auth";
import { request } from "./client";
import type { Premises } from "./premises";

export type ApplicationStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "SCRUTINY"
  | "INFO_REQUIRED"
  | "INSPECTION_PENDING"
  | "REVIEW_PENDING"
  | "COMPLIANCE_PENDING"
  | "APPROVED_PENDING_ISSUE"
  | "COMPLETED"
  | "REJECTED"
  | "WITHDRAWN";

export interface CaseSummary {
  application_id: string;
  draft_reference: string;
  public_reference: string | null;
  status: ApplicationStatus;
  service_key: string;
  premises: { premises_id: string; display_name: string; category_key: string; locality: string };
  owner_queue: string;
  submitted_at: string | null;
  next_due_at: string | null;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface AllowedAction {
  key: string;
  enabled: boolean;
  reason_code: string | null;
}

export interface DocumentVersion {
  document_version_id: string;
  application_id: string | null;
  requirement_code: string;
  original_name: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  scan_state: "QUARANTINED" | "CLEAN" | "REJECTED";
  scan_detail: string;
  scanned_at: string | null;
  uploaded_at: string;
  version: number;
}

export interface Requirement {
  code: string;
  label: string;
  required: boolean;
  status: "MISSING" | "PENDING_SCAN" | "REJECTED" | "SATISFIED";
  document_version_id: string | null;
}

export interface Declaration {
  code: string;
  version: string;
  text: string;
}

export interface DeclarationDraft {
  code: string;
  version: string;
  accepted: boolean;
}

export type DraftFields = Record<string, string | number | null | undefined>;

export interface Draft {
  draft_revision: number;
  form_schema_ref: string;
  saved_at: string | null;
  fields: DraftFields;
  declaration_drafts: DeclarationDraft[];
  declarations: Declaration[];
  attachment_links: string[];
  documents: DocumentVersion[];
  requirements: Requirement[];
  blockers: { code: string; pointer: string }[];
}

export interface ObligationSummary {
  obligation_id: string;
  kind: string;
  state: string;
  time_basis: string;
  budget_minutes: number;
  started_at: string;
  due_at: string | null;
  owner_queue: string;
}

export interface CaseDetail extends CaseSummary {
  owner_queue_key: string;
  premises_detail: Premises;
  policy: {
    applicable: boolean;
    policy_version_id: string | null;
    policy_number: number | null;
    explanation: string;
    inspection_required: boolean | null;
    pinned_policy_version_id: string | null;
  };
  draft: Draft | null;
  submission: {
    number: number;
    accepted_at: string;
    policy_version_id: string;
    policy_number: number;
    sha256: string;
    fields: DraftFields;
    documents: { requirement_code: string; document_version_id: string }[];
  } | null;
  obligations: ObligationSummary[];
  inspections: {
    inspection_id: string;
    attempt_number: number;
    purpose: string;
    status: string;
    scheduled_start: string | null;
    scheduled_end: string | null;
    appointment_timezone: string;
    officer_name: string | null;
    failed_reason_code: string | null;
    report?: {
      report_id?: string;
      revision_number: number;
      accepted_at: string;
      eligible_for_review?: boolean | null;
      blockers?: { code: string; item_code?: string; message?: string }[];
      na_requiring_review?: string[];
    } | null;
  }[];
  routing_exception: {
    exception_id: string;
    code: string;
    input: Record<string, unknown>;
    owner_queue: string;
    routing_artifact_id: string | null;
  } | null;
  notices: {
    notice_id: string;
    type: "INFORMATION" | "DEFICIENCY";
    round_number: number;
    state: string;
    published_at: string;
    due_at: string | null;
    items_total: number;
    open_items: number;
    internal_note: string | null;
  }[];
  findings_summary: { open_mandatory: number; open_advisory: number; verified_closed: number; reinspection_outstanding: string[] } | null;
  /** Outcome / issuance summary (B12). Applicants receive the public decision only. */
  decision: {
    decision_id: string;
    decision_number: number;
    kind: "APPROVE" | "REJECT";
    public_reason: string;
    accepted_at: string;
    submission_revision_id: string;
    report_id: string | null;
    policy_version_id: string;
    reason?: string;
    actor_id?: string;
    authority_grant_id?: string;
  } | null;
  issuance: {
    issuance_request_id: string;
    certificate_number: string;
    state: "READY" | "PROCESSING" | "RECONCILIATION_REQUIRED" | "PUBLISHED" | "FAILED";
    published_at: string | null;
    attempts?: number;
    last_error_code?: string | null;
  } | null;
  certificate: {
    certificate_id: string;
    certificate_number: string;
    effective_status: string;
    issued_at: string;
    valid_until: string | null;
    is_demo: boolean;
  } | null;
  decision_readiness: Record<string, unknown> | null;
  allowed_actions: AllowedAction[];
}

interface Page<T> {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
}

export function applicationsQuery(params: { status?: string; q?: string; cursor?: string } = {}) {
  const search = new URLSearchParams();
  if (params.status) search.set("status", params.status);
  if (params.q) search.set("q", params.q);
  if (params.cursor) search.set("cursor", params.cursor);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return queryOptions({
    queryKey: ["applications", "list", params.status ?? "", params.q ?? "", params.cursor ?? ""] as const,
    queryFn: async ({ signal }) => (await request<{ data: Page<CaseSummary> }>(`/applications${suffix}`, { signal })).data.data,
  });
}

export function applicationQuery(applicationId: string) {
  return queryOptions({
    queryKey: ["applications", "detail", applicationId] as const,
    queryFn: async ({ signal }) => {
      const response = await request<{ data: CaseDetail }>(`/applications/${applicationId}`, { signal });
      return { detail: response.data.data, etag: response.etag ?? "" };
    },
  });
}

export async function createDraft(input: { premises_id: string; service_id: string }, idempotencyKey: string) {
  await ensureCsrf();
  const response = await request<{ data: { application_id: string; draft_reference: string } }>("/applications", {
    method: "POST",
    body: input,
    idempotencyKey,
  });
  return { ...response.data.data, etag: response.etag ?? "" };
}

export interface DraftPatch {
  draft_revision: number;
  fields?: DraftFields;
  declaration_drafts?: DeclarationDraft[];
  attachment_links?: string[];
}

export interface SavedDraft extends Draft {
  application_id: string;
  version: number;
}

export async function saveDraft(applicationId: string, patch: DraftPatch, etag: string, idempotencyKey: string) {
  await ensureCsrf();
  const response = await request<{ data: SavedDraft }>(`/applications/${applicationId}/draft`, {
    method: "PATCH",
    body: patch,
    ifMatch: etag,
    idempotencyKey,
  });
  return { draft: response.data.data, etag: response.etag ?? "" };
}

// ---- documents (FR-05) --------------------------------------------------------------------

export interface UploadTicket {
  upload_id: string;
  upload_url: string;
  upload_method: "PUT";
  upload_headers: Record<string, string>;
  expires_at: string;
  version: number;
}

export async function sha256Hex(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** Reserve -> PUT bytes -> complete. Returns the QUARANTINED document version. */
export function uploadDocument(applicationId: string, requirementCode: string, file: File): Promise<DocumentVersion> {
  return uploadFile("APPLICATION_DRAFT", applicationId, requirementCode, file);
}

export type UploadTargetType = "APPLICATION_DRAFT" | "INSPECTION_EVIDENCE" | "NOTICE_RESPONSE";

/** Shared upload flow for every permitted target type (the server decides who may upload where). */
export async function uploadFile(targetType: UploadTargetType, targetId: string, requirementCode: string, file: File): Promise<DocumentVersion> {
  await ensureCsrf();
  const digest = await sha256Hex(file);
  const reserved = await request<{ data: UploadTicket }>("/uploads", {
    method: "POST",
    body: {
      target_type: targetType,
      target_id: targetId,
      original_name: file.name,
      media_type: file.type,
      size_bytes: file.size,
      sha256: digest,
      requirement_code: requirementCode,
    },
    idempotencyKey: crypto.randomUUID(),
  });
  const ticket = reserved.data.data;
  const token = document.cookie
    .split(";")
    .map((c) => c.trim())
    .find((c) => c.startsWith("csrftoken="))
    ?.slice("csrftoken=".length);
  const put = await fetch(ticket.upload_url, {
    method: "PUT",
    headers: { "Content-Type": file.type, ...(token ? { "X-CSRFToken": decodeURIComponent(token) } : {}) },
    body: file,
    credentials: "same-origin",
  });
  if (!put.ok) {
    const body = (await put.json().catch(() => null)) as { detail?: string; code?: string } | null;
    throw new Error(body?.detail ?? `Upload failed (${put.status})`);
  }
  const completed = await request<{ data: DocumentVersion }>(`/uploads/${ticket.upload_id}/complete`, {
    method: "POST",
    body: { sha256: digest, size_bytes: file.size },
    ifMatch: reserved.etag ?? `"upload:${ticket.upload_id}:v${ticket.version}"`,
    idempotencyKey: crypto.randomUUID(),
  });
  return completed.data.data;
}

export async function fetchDocument(documentId: string): Promise<DocumentVersion> {
  return (await request<{ data: DocumentVersion }>(`/documents/${documentId}`)).data.data;
}

export async function requestDocumentAccess(documentId: string, purpose: "PREVIEW" | "DOWNLOAD"): Promise<string> {
  await ensureCsrf();
  const response = await request<{ data: { url: string } }>(`/documents/${documentId}/access`, {
    method: "POST",
    body: { purpose },
    idempotencyKey: crypto.randomUUID(),
  });
  return response.data.data.url;
}
