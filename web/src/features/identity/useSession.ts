import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { logout, sessionQuery, type Principal } from "../../api/auth";

export interface SessionState {
  principal: Principal | null;
  isLoading: boolean;
  isError: boolean;
  /** The bootstrap failure (ApiError for a problem such as 503, NetworkError otherwise). */
  error: unknown;
  refetch: () => Promise<unknown>;
}

export function useSession(): SessionState {
  const query = useQuery(sessionQuery);
  return {
    principal: query.data ?? null,
    isLoading: query.isPending,
    isError: query.isError,
    error: query.error,
    refetch: () => query.refetch(),
  };
}

/** Clears every cached server-state entry on identity change (engineering standards s.3). */
export function useSignOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: logout,
    onSettled: async () => {
      // Observers must see "no session" immediately; then drop every other cached entry.
      queryClient.setQueryData(sessionQuery.queryKey, null);
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== "session" });
      await queryClient.invalidateQueries({ queryKey: ["session"] });
    },
  });
}

/** Only relative, same-origin paths are honoured as post-sign-in destinations (UI-02). */
export function safeNext(raw: string | null | undefined, fallback = "/"): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) {
    return fallback;
  }
  return raw;
}
