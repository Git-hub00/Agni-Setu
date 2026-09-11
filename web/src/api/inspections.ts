/**
 * Inspection endpoints API-029, 038..044, 046, 094 and the scoped officer roster. Child commands
 * carry the application version in the body (docs/24 s.5) and the inspection ETag in If-Match.
 */

import { queryOptions } from "@tanstack/react-query";

import { ensureCsrf } from "./auth";
import { request } from "./client";

export type InspectionStatus = "REQUESTED" | "SCHEDULED" | "IN_PROGRESS" | "COMPLETED" | "FAILED" | "CANCELLED";

export interface AssignmentSummary {
  assignment_id: string;
  number: number;
  state: "ACTIVE" | "SUPERSEDED" | "REVOKED" | "FULFILLED";
  officer_id: string;
  officer_name: string;
  reason: string;
  booking_start: string | null;
  booking_end: string | null;
  version: number;
}

export interface Inspection {
  inspection_id: string;
  application_id: string;
  public_reference: string | null;
  application_status: string;
  application_version: number;
  attempt_number: number;
  purpose: string;
  parent_inspection_id: string | null;
  status: InspectionStatus;
  checklist_ref: string;
  premises: { display_name: string; locality: string; category_key: string; ward_key: string };
  owner_queue: string;
  scheduled_start: string | null;
  scheduled_end: string | null;
  appointment_timezone: string;
  started_at: string | null;
  finished_at: string | null;
  check_in: Record<string, unknown> | null;
  failed_reason_code: string | null;
  failed_notes: string | null;
  cancel_reason: string | null;
  current_assignment: AssignmentSummary | null;
  version: number;
  updated_at: string;
}

export interface ChecklistItem {
  code: string;
  title: string;
  mandatory: boolean;
  evidence_required: boolean;
  na_permitted: boolean;
}

export interface InspectionDetail extends Inspection {
  checklist_items: ChecklistItem[];
  assignments: Omit<AssignmentSummary, "version">[];
  allowed_actions: { key: string; enabled: boolean; reason_code: string | null }[];
}

export function inspectionsQuery(params: { state?: string[]; unassigned?: boolean } = {}) {
  const search = new URLSearchParams();
  for (const s of params.state ?? []) search.append("state", s);
  if (params.unassigned) search.set("unassigned", "true");
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return queryOptions({
    queryKey: ["inspections", "list", (params.state ?? []).join(","), params.unassigned ? "1" : "0"] as const,
    queryFn: async ({ signal }) =>
      (await request<{ data: { items: Inspection[]; as_of: string } }>(`/inspections${suffix}`, { signal })).data.data,
  });
}

export function inspectionQuery(inspectionId: string) {
  return queryOptions({
    queryKey: ["inspections", "detail", inspectionId] as const,
    queryFn: async ({ signal }) => {
      const response = await request<{ data: InspectionDetail }>(`/inspections/${inspectionId}`, { signal });
      return { inspection: response.data.data, etag: response.etag ?? "" };
    },
  });
}

export interface ScheduleWindow {
  starts_at: string;
  ends_at: string;
  timezone: string;
  officers: { officer_id: string; display_name: string }[];
  bookings: { assignment_id: string; inspection_id: string; officer_id: string; officer_name: string; booking_start: string | null; booking_end: string | null; public_reference: string | null; inspection_status: string }[];
  unavailability: { availability_id: string; officer_id: string; kind: string; starts_at: string; ends_at: string; reason_code: string }[];
  as_of: string;
}

export function scheduleQuery(startsAt: string, endsAt: string) {
  const search = new URLSearchParams({ starts_at: startsAt, ends_at: endsAt });
  return queryOptions({
    queryKey: ["schedule", startsAt, endsAt] as const,
    queryFn: async ({ signal }) => (await request<{ data: ScheduleWindow }>(`/schedule?${search.toString()}`, { signal })).data.data,
  });
}

export const officersQuery = queryOptions({
  queryKey: ["officers"] as const,
  queryFn: async ({ signal }) => (await request<{ data: { items: { officer_id: string; display_name: string }[] } }>("/officers", { signal })).data.data.items,
});

async function command<T>(path: string, body: Record<string, unknown>, etag: string): Promise<{ data: T; etag: string }> {
  await ensureCsrf();
  const response = await request<{ data: T }>(path, { method: "POST", body, ifMatch: etag, idempotencyKey: crypto.randomUUID() });
  return { data: response.data.data, etag: response.etag ?? "" };
}

export function requireInspection(applicationId: string, reason: string, etag: string) {
  return command<Inspection>(`/applications/${applicationId}/require-inspection`, { purpose: "INITIAL", reason }, etag);
}

export function scheduleInspection(inspection: Inspection, input: { officer_id: string; starts_at: string; ends_at: string; reason: string }, etag: string) {
  return command<Inspection>(`/inspections/${inspection.inspection_id}/schedule`, { ...input, appointment_timezone: "Asia/Kolkata", application_version: inspection.application_version }, etag);
}

export function reassignInspection(inspection: Inspection, input: { new_officer_id: string; reason: string }, etag: string) {
  return command<Inspection>(`/inspections/${inspection.inspection_id}/reassign`, { ...input, application_version: inspection.application_version }, etag);
}

export function cancelInspection(inspection: Inspection, reason: string, etag: string) {
  return command<Inspection & { next_attempt_id: string }>(`/inspections/${inspection.inspection_id}/cancel`, { reason, application_version: inspection.application_version }, etag);
}

export function checkIn(inspection: Inspection, input: { location_unavailable_reason?: string; latitude?: number; longitude?: number; accuracy_m?: number; notes?: string }, etag: string) {
  const assignment = inspection.current_assignment;
  return command<Inspection>(
    `/inspections/${inspection.inspection_id}/check-in`,
    { ...input, application_version: inspection.application_version, assignment_version: assignment?.version ?? 0, captured_at: new Date().toISOString() },
    etag,
  );
}

export function failVisit(inspection: Inspection, input: { reason_code: string; reason: string }, etag: string) {
  const assignment = inspection.current_assignment;
  return command<Inspection & { next_attempt_id: string }>(
    `/inspections/${inspection.inspection_id}/fail-visit`,
    { ...input, application_version: inspection.application_version, assignment_version: assignment?.version ?? 0, captured_at: new Date().toISOString() },
    etag,
  );
}

export const FAILED_VISIT_REASONS = ["SITE_INACCESSIBLE", "APPLICANT_UNAVAILABLE", "SAFETY_CONCERN", "WEATHER", "OFFICER_UNAVAILABLE", "OTHER"] as const;
