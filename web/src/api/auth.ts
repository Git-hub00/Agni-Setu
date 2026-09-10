/**
 * Identity endpoints API-001..007. Sessions are HttpOnly cookies; the browser never sees a
 * token. The CSRF cookie is bootstrapped before the first unsafe request.
 */

import { queryOptions } from "@tanstack/react-query";

import { ApiError } from "./errors";
import { readCookie, request } from "./client";

export type Workspace = "applicant" | "officer" | "supervisor" | "leadership" | "admin" | "policy" | "public";

export interface Principal {
  id: string;
  display_name: string;
  kind: "APPLICANT" | "STAFF" | "SERVICE";
  workspaces: Workspace[];
  active_workspace: Workspace;
  scopes: string[];
  capabilities: string[];
  authz_epoch: number;
  session_expires_at: string | null;
  feature_gates: { service_mode: "DEMO" | "LIVE"; demo_controls: boolean; staff_oidc: boolean };
}

export interface ChallengeStarted {
  challenge_id: string;
  masked_destination: string;
  expires_at: string;
  resend_available_at: string;
}

export type Channel = "EMAIL" | "SMS";

export async function ensureCsrf(): Promise<void> {
  if (readCookie("csrftoken")) {
    return;
  }
  await request<{ csrf_token: string }>("/auth/csrf");
}

export async function startOtp(channel: Channel, contact: string): Promise<ChallengeStarted> {
  await ensureCsrf();
  const response = await request<{ data: ChallengeStarted }>("/auth/otp/challenges", {
    method: "POST",
    body: { channel, contact },
  });
  return response.data.data;
}

export async function verifyOtp(input: {
  challengeId: string;
  code: string;
  channel: Channel;
  contact: string;
}): Promise<Principal> {
  await ensureCsrf();
  const response = await request<{ data: Principal }>("/auth/otp/verify", {
    method: "POST",
    body: { challenge_id: input.challengeId, code: input.code, channel: input.channel, contact: input.contact },
  });
  return response.data.data;
}

/** Resolves to null when there is no valid session (401) instead of throwing. */
export async function fetchMe(signal?: AbortSignal): Promise<Principal | null> {
  try {
    const response = await request<{ data: Principal }>("/me", { signal });
    return response.data.data;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null;
    }
    throw error;
  }
}

export async function logout(): Promise<void> {
  await ensureCsrf();
  await request<null>("/auth/logout", { method: "POST" });
}

export const sessionQuery = queryOptions({
  queryKey: ["session", "me"] as const,
  queryFn: ({ signal }) => fetchMe(signal),
  staleTime: 30_000,
  retry: false,
});

export function staffSignInUrl(next: string): string {
  return `/api/v1/auth/oidc/start?next=${encodeURIComponent(next)}`;
}
