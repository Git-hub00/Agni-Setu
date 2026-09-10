/**
 * Service catalogue (API-018) and nonbinding applicability preview (API-019). The preview never
 * decides anything: submission revalidates against the policy effective at that instant.
 */

import { queryOptions } from "@tanstack/react-query";

import { ensureCsrf } from "./auth";
import { request } from "./client";

export interface ServiceSummary {
  service_id: string;
  key: string;
  title: string;
  mode: "DEMO" | "STANDALONE" | "INTEGRATED_MONITORING";
  available: boolean;
  explanation: string;
  allowed_categories: string[];
}

export interface Applicability {
  applicable: boolean;
  explanation: string;
  policy_version_id: string | null;
  policy_number: number | null;
  payload_sha256: string | null;
  form_schema_ref: string | null;
  checklist_ref: string | null;
  required_documents: string[];
  inspection_required: boolean | null;
  allowed_categories: string[];
  binding: false;
}

export const servicesQuery = queryOptions({
  queryKey: ["services", "catalogue"] as const,
  queryFn: async ({ signal }) =>
    (await request<{ data: { items: ServiceSummary[] } }>("/services", { signal })).data.data.items,
});

export async function checkApplicability(serviceId: string, declaredCategory: string): Promise<Applicability> {
  await ensureCsrf();
  const response = await request<{ data: Applicability }>(`/services/${serviceId}/applicability`, {
    method: "POST",
    body: { declared_category: declaredCategory },
  });
  return response.data.data;
}
