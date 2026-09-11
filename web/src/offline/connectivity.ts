/**
 * Connectivity is API reachability plus a live session for the same principal, never
 * `navigator.onLine` alone (docs/09 s.4). The four surfaced states are distinct so a captive
 * portal or an expired session is not reported as "offline".
 */

import { request } from "../api/client";
import { ApiError, NetworkError } from "../api/errors";
import type { Principal } from "../api/auth";

export type Connectivity =
  | { state: "ONLINE"; principal: Principal }
  | { state: "OFFLINE" }
  | { state: "SERVER_UNAVAILABLE" }
  | { state: "SIGN_IN_NEEDED" };

export async function probeConnectivity(): Promise<Connectivity> {
  if (typeof navigator !== "undefined" && "onLine" in navigator && !navigator.onLine) {
    return { state: "OFFLINE" };
  }
  try {
    const me = await request<{ data: Principal }>("/me");
    return { state: "ONLINE", principal: me.data.data };
  } catch (error) {
    if (error instanceof NetworkError) return { state: "OFFLINE" };
    if (error instanceof ApiError) {
      if (error.status === 401) return { state: "SIGN_IN_NEEDED" };
      if (error.status >= 500) return { state: "SERVER_UNAVAILABLE" };
    }
    return { state: "SERVER_UNAVAILABLE" };
  }
}
