/**
 * Support tickets and profile-gated routes (API-112..118; FR-30; UI-26). A ticket is a help
 * conversation with its own lifecycle; it never changes a case and is not a legal appeal.
 */

import { queryOptions } from "@tanstack/react-query";

import { ensureCsrf } from "./auth";
import { request } from "./client";

export type TicketState = "OPEN" | "IN_PROGRESS" | "WAITING_FOR_REQUESTER" | "RESOLVED" | "CLOSED";
export type TicketCategory = "HOW_TO" | "TECHNICAL" | "ACCESS" | "DATA_CORRECTION" | "OTHER";
export const TICKET_CATEGORIES: TicketCategory[] = ["HOW_TO", "TECHNICAL", "ACCESS", "DATA_CORRECTION", "OTHER"];
export const TICKET_STATES: TicketState[] = ["OPEN", "IN_PROGRESS", "WAITING_FOR_REQUESTER", "RESOLVED", "CLOSED"];

export interface Ticket {
  ticket_id: string;
  category: TicketCategory;
  subject: string;
  description: string;
  state: TicketState;
  priority: "NORMAL" | "URGENT";
  application_id: string | null;
  public_reference: string | null;
  owner_queue: string;
  requester_id: string;
  resolved_at: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
  version: number;
  etag: string;
  notice: string;
}

export interface TicketMessage {
  message_id: string;
  kind: "MESSAGE" | "STATUS";
  audience: "REQUESTER" | "INTERNAL";
  sender_id: string;
  body: string;
  document_version_ids: string[];
  state_after: string | null;
  created_at: string;
}

export interface TicketAction {
  key: string;
  enabled: boolean;
  reason_code: string | null;
}

export interface TicketDetail extends Ticket {
  messages: TicketMessage[];
  is_requester: boolean;
  support_scope: boolean;
  allowed_actions: TicketAction[];
}

export interface SupportRoutes {
  appeals: { enabled: boolean; referral_text: string };
  external_registration: { enabled: boolean };
  fees: { enabled: boolean };
  continuing_declarations: { enabled: boolean };
  policy_present: boolean;
}

export interface TicketList {
  items: Ticket[];
  as_of: string;
  support_scope: boolean;
  routes: SupportRoutes;
}

export function ticketsQuery(params: { state?: string; application_id?: string } = {}) {
  const search = new URLSearchParams();
  if (params.state) search.set("state", params.state);
  if (params.application_id) search.set("application_id", params.application_id);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return queryOptions({
    queryKey: ["tickets", "list", params.state ?? "", params.application_id ?? ""] as const,
    queryFn: async ({ signal }) => (await request<{ data: TicketList }>(`/tickets${suffix}`, { signal })).data.data,
  });
}

export function ticketQuery(ticketId: string) {
  return queryOptions({
    queryKey: ["tickets", "detail", ticketId] as const,
    queryFn: async ({ signal }) => {
      const response = await request<{ data: TicketDetail }>(`/tickets/${ticketId}`, { signal });
      return { ticket: response.data.data, etag: response.etag ?? "" };
    },
  });
}

export const supportRoutesQuery = queryOptions({
  queryKey: ["support", "routes"] as const,
  queryFn: async ({ signal }) => (await request<{ data: SupportRoutes }>("/support/routes", { signal })).data.data,
});

export interface TicketCreateInput {
  category: TicketCategory;
  subject: string;
  description: string;
  application_id?: string;
  document_version_ids?: string[];
}

export async function createTicket(input: TicketCreateInput): Promise<TicketDetail> {
  await ensureCsrf();
  const response = await request<{ data: TicketDetail }>("/tickets", { method: "POST", body: input, idempotencyKey: crypto.randomUUID() });
  return response.data.data;
}

async function command<T>(path: string, body: Record<string, unknown>, etag: string): Promise<T> {
  await ensureCsrf();
  const response = await request<{ data: T }>(path, { method: "POST", body, ifMatch: etag, idempotencyKey: crypto.randomUUID() });
  return response.data.data;
}

/** API-115. */
export function addTicketMessage(ticketId: string, input: { body: string; audience: "REQUESTER" | "INTERNAL"; document_version_ids?: string[] }, etag: string) {
  return command<TicketMessage & { ticket_state: TicketState }>(`/tickets/${ticketId}/messages`, { ...input }, etag);
}

/** API-116. */
export function changeTicketStatus(ticketId: string, input: { state: TicketState; reason: string; next_action?: string }, etag: string) {
  return command<Ticket>(`/tickets/${ticketId}/status`, { ...input }, etag);
}
