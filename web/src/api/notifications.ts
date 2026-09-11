/**
 * Personal notifications (API-078..080) and preferences (API-008), UI-19. Read markers are
 * idempotent and never change case state; delivery status is shown to the recipient only.
 */

import { queryOptions } from "@tanstack/react-query";

import { ensureCsrf } from "./auth";
import { request } from "./client";

export interface Delivery {
  channel: "EMAIL" | "SMS";
  state: "READY" | "SENDING" | "ACCEPTED_BY_PROVIDER" | "DELIVERED" | "FAILED" | "UNKNOWN";
  destination_masked: string | null;
  sent_at: string | null;
  failure_code: string | null;
  attempts: number;
}

export interface Notification {
  notification_id: string;
  category: string;
  mandatory: boolean;
  title: string;
  body: string;
  target_path: string | null;
  application_id: string | null;
  created_at: string;
  read_at: string | null;
  deliveries: Delivery[];
}

export interface NotificationPage {
  items: Notification[];
  next_cursor: string | null;
  has_more: boolean;
  unread_count: number;
  as_of: string;
}

export function notificationsQuery(unreadOnly: boolean) {
  return queryOptions({
    queryKey: ["notifications", unreadOnly ? "unread" : "all"] as const,
    queryFn: async ({ signal }) =>
      (await request<{ data: NotificationPage }>(`/notifications${unreadOnly ? "?unread_only=true" : ""}`, { signal })).data.data,
  });
}

export async function markRead(notificationId: string): Promise<Notification> {
  await ensureCsrf();
  const response = await request<{ data: Notification }>(`/notifications/${notificationId}/read`, {
    method: "POST",
    body: {},
    idempotencyKey: crypto.randomUUID(),
  });
  return response.data.data;
}

/** Marks read only up to the boundary the user saw; later arrivals stay unread. */
export async function readThrough(through: string): Promise<{ marked_read: number; unread_count: number }> {
  await ensureCsrf();
  const response = await request<{ data: { marked_read: number; unread_count: number } }>("/notifications/read-through", {
    method: "POST",
    body: { through },
    idempotencyKey: crypto.randomUUID(),
  });
  return response.data.data;
}

export interface Preferences {
  locale: string;
  optional_channels: ("EMAIL" | "SMS")[];
  reduced_motion: boolean;
  mandatory_note: string;
}

export const preferencesQuery = queryOptions({
  queryKey: ["preferences"] as const,
  queryFn: async ({ signal }) => (await request<{ data: Preferences }>("/me/preferences", { signal })).data.data,
});

export async function updatePreferences(input: { locale: string; optional_channels: string[]; reduced_motion: boolean }): Promise<Preferences> {
  await ensureCsrf();
  const response = await request<{ data: Preferences }>("/me/preferences", { method: "PATCH", body: { ...input } });
  return response.data.data;
}
