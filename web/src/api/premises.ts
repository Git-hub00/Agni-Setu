/**
 * Premises endpoints API-010..013 (FR-03). Every write is a kernel command: it carries an
 * Idempotency-Key, and edits carry the If-Match ETag read from the detail response.
 */

import { queryOptions } from "@tanstack/react-query";

import { ensureCsrf } from "./auth";
import { request } from "./client";

export interface Premises {
  premises_id: string;
  owner_id: string;
  display_name: string;
  address_line1: string;
  address_line2: string;
  locality: string;
  ward_key: string;
  postal_code: string;
  category_key: string;
  area_sqm: string;
  height_m: string;
  floor_count: number;
  occupancy_count: number | null;
  version: number;
  updated_at: string;
}

export interface PremisesInput {
  display_name: string;
  address_line1: string;
  address_line2?: string;
  locality: string;
  ward_key: string;
  postal_code: string;
  category_key: string;
  area_sqm: string;
  height_m: string;
  floor_count: number;
  occupancy_count?: number | null;
}

interface Page<T> {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
}

export const premisesListQuery = queryOptions({
  queryKey: ["premises", "list"] as const,
  queryFn: async ({ signal }) => (await request<{ data: Page<Premises> }>("/premises", { signal })).data.data.items,
});

export function premisesDetailQuery(premisesId: string) {
  return queryOptions({
    queryKey: ["premises", "detail", premisesId] as const,
    queryFn: async ({ signal }) => {
      const response = await request<{ data: Premises }>(`/premises/${premisesId}`, { signal });
      return { premises: response.data.data, etag: response.etag };
    },
  });
}

export async function registerPremises(input: PremisesInput, idempotencyKey: string): Promise<{ premises_id: string }> {
  await ensureCsrf();
  const response = await request<{ data: { premises_id: string } }>("/premises", {
    method: "POST",
    body: input,
    idempotencyKey,
  });
  return response.data.data;
}

export async function updatePremises(
  premisesId: string,
  patch: Partial<PremisesInput>,
  etag: string,
  idempotencyKey: string,
): Promise<void> {
  await ensureCsrf();
  await request(`/premises/${premisesId}`, { method: "PATCH", body: patch, ifMatch: etag, idempotencyKey });
}
