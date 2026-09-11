/**
 * Notices, responses, item review, finding verification and correction-cycle transitions
 * (API-053..062). Commands carry If-Match for the resource in the route (case, notice, item or
 * finding) and the current application version in the body where the contract asks for it.
 */

import { queryOptions } from "@tanstack/react-query";

import { uploadFile, type DocumentVersion } from "./applications";
import { ensureCsrf } from "./auth";
import { request } from "./client";

export type NoticeType = "INFORMATION" | "DEFICIENCY";
export type NoticeState = "DRAFT" | "PUBLISHED" | "SATISFIED" | "SUPERSEDED" | "CANCELLED";
export type ItemState = "OPEN" | "RESPONSE_RECEIVED" | "UNDER_REVIEW" | "ACCEPTED" | "RETURNED";
export type FindingState = "OPEN" | "RESPONSE_RECEIVED" | "UNDER_REVIEW" | "VERIFIED_CLOSED";

export interface ResponseRevision {
  response_revision_id: string;
  number: number;
  explanation: string;
  document_version_ids: string[];
  accepted_at: string;
  sha256: string;
}

export interface NoticeItem {
  notice_item_id: string;
  notice_id: string;
  code: string;
  title: string;
  description: string;
  required: boolean;
  acceptable_evidence_types: string[];
  public_guidance: string | null;
  state: ItemState;
  finding_id: string | null;
  finding_state: FindingState | null;
  finding_severity: "MANDATORY" | "ADVISORY" | null;
  reviewer_feedback: string | null;
  current_response_id: string | null;
  verified_at: string | null;
  version: number;
  responses: ResponseRevision[];
  reviews: { review_id: string; outcome: string; reason: string; response_revision_id: string | null; accepted_at: string }[];
}

export interface Notice {
  notice_id: string;
  application_id: string;
  round_number: number;
  type: NoticeType;
  state: NoticeState;
  public_reason: string;
  published_at: string;
  response_budget_minutes: number;
  due_at: string | null;
  obligation_state: string | null;
  supersedes_id: string | null;
  superseded_by_id: string | null;
  closed_at: string | null;
  version: number;
  internal_note?: string | null;
  items: NoticeItem[];
  open_items: number;
  items_total: number;
}

export interface NoticeDetail extends Notice {
  application_status: string;
  application_version: number;
  public_reference: string | null;
  evidence_types: string[];
  allowed_actions: { key: string; enabled: boolean; reason_code: string | null }[];
}

export interface Finding {
  finding_id: string;
  application_id: string;
  originating_report_id: string;
  checklist_item_code: string;
  severity: "MANDATORY" | "ADVISORY";
  state: FindingState;
  description: string;
  reinspection_required: boolean;
  current_response_id: string | null;
  closed_at: string | null;
  last_review_reason: string | null;
  version: number;
  etag: string;
}

export function noticesQuery(applicationId: string) {
  return queryOptions({
    queryKey: ["notices", "list", applicationId] as const,
    queryFn: async ({ signal }) => (await request<{ data: { items: Notice[]; evidence_types: string[]; as_of: string } }>(`/applications/${applicationId}/notices`, { signal })).data.data,
  });
}

export function noticeQuery(noticeId: string) {
  return queryOptions({
    queryKey: ["notices", "detail", noticeId] as const,
    queryFn: async ({ signal }) => {
      const response = await request<{ data: NoticeDetail }>(`/notices/${noticeId}`, { signal });
      return { notice: response.data.data, etag: response.etag ?? "" };
    },
  });
}

export function findingsQuery(applicationId: string) {
  return queryOptions({
    queryKey: ["findings", applicationId] as const,
    queryFn: async ({ signal }) => (await request<{ data: { items: Finding[]; as_of: string } }>(`/applications/${applicationId}/findings`, { signal })).data.data.items,
  });
}

async function command<T>(path: string, body: Record<string, unknown>, etag: string, key?: string): Promise<{ data: T; etag: string }> {
  await ensureCsrf();
  const response = await request<{ data: T }>(path, { method: "POST", body, ifMatch: etag, idempotencyKey: key ?? crypto.randomUUID() });
  return { data: response.data.data, etag: response.etag ?? "" };
}

export interface NoticeItemInput {
  code: string;
  title: string;
  description: string;
  required: boolean;
  acceptable_evidence_types: string[];
  public_guidance?: string;
  finding_id?: string;
}

export interface NoticeCreate {
  type: NoticeType;
  public_reason: string;
  internal_note?: string;
  items: NoticeItemInput[];
  proposed_response_budget_minutes?: number;
  supersedes_notice_id?: string;
}

/** API-054 (TR-03 / TR-07). */
export function publishNotice(applicationId: string, body: NoticeCreate, etag: string) {
  return command<Notice & { application_status: string; application_version: number }>(`/applications/${applicationId}/notices`, { ...body }, etag);
}

/** API-056: one new revision per item; never closes anything. */
export function submitResponse(notice: NoticeDetail, responses: { notice_item_id: string; explanation: string; document_version_ids: string[] }[], etag: string, key: string) {
  return command<Notice & { responses: { code: string; number: number; item_state: ItemState }[] }>(
    `/notices/${notice.notice_id}/responses`,
    { application_version: notice.application_version, responses, declaration_accepted: true },
    etag,
    key,
  );
}

/** Applicant evidence for one notice item (NOTICE_RESPONSE target). */
export function uploadResponseEvidence(noticeId: string, itemCode: string, file: File): Promise<DocumentVersion> {
  return uploadFile("NOTICE_RESPONSE", noticeId, `response-${itemCode.toLowerCase()}`, file);
}

/** API-058. */
export function reviewItem(notice: NoticeDetail, item: NoticeItem, input: { outcome: "ACCEPTED" | "RETURNED"; reason: string }) {
  return command<NoticeItem>(
    `/notice-items/${item.notice_item_id}/review`,
    { application_version: notice.application_version, response_revision_id: item.current_response_id, ...input },
    `"notice_item:${item.notice_item_id}:v${item.version}"`,
  );
}

/** API-060. */
export function verifyFinding(
  finding: Finding,
  applicationVersion: number,
  input: { outcome: "VERIFIED_CLOSED" | "RETURNED" | "REINSPECTION_REQUIRED"; reason: string; response_revision_id: string | null; evidence_document_ids: string[]; report_id?: string },
) {
  return command<Finding>(`/findings/${finding.finding_id}/verify`, { application_version: applicationVersion, ...input }, finding.etag);
}

/** API-057 (TR-04). */
export function acceptInformation(notice: NoticeDetail, reason: string, etag: string) {
  return command<Notice & { application_status: string }>(`/notices/${notice.notice_id}/accept-information`, { reason }, etag);
}

/** API-061 (TR-08). */
export function completeCorrections(applicationId: string, reason: string, etag: string) {
  return command<{ status: string }>(`/applications/${applicationId}/complete-corrections`, { reason }, etag);
}

/** API-062 (TR-09). */
export function requireReinspection(applicationId: string, input: { finding_ids: string[]; reason: string; previous_inspection_id: string }, etag: string) {
  return command<{ inspection_id: string; attempt_number: number }>(`/applications/${applicationId}/reinspect`, { ...input }, etag);
}
