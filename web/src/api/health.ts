/**
 * API-121 / API-122 health probes. Readiness intentionally returns 503 with the same body shape
 * when a check fails, so the query resolves to a value instead of throwing for that case.
 */

import { queryOptions } from "@tanstack/react-query";

import { ApiError } from "./errors";
import { request } from "./client";

export type CheckResult = "pass" | "fail";

export interface ReadinessBody {
  status: "ready" | "not_ready";
  checks: Record<string, CheckResult>;
  service_mode: "DEMO" | "LIVE";
}

export async function fetchReadiness(signal?: AbortSignal): Promise<ReadinessBody> {
  try {
    const response = await request<ReadinessBody>("/health/ready", { signal });
    return response.data;
  } catch (error) {
    if (error instanceof ApiError && error.status === 503 && isReadinessBody(error.body)) {
      return error.body;
    }
    throw error;
  }
}

function isReadinessBody(value: unknown): value is ReadinessBody {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    (candidate.status === "ready" || candidate.status === "not_ready") &&
    typeof candidate.checks === "object" &&
    candidate.checks !== null
  );
}

export const readinessQuery = queryOptions({
  queryKey: ["health", "ready"] as const,
  queryFn: ({ signal }) => fetchReadiness(signal),
  staleTime: 10_000,
  refetchInterval: 15_000,
  retry: false,
});
