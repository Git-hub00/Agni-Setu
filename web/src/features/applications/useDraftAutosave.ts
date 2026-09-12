import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { saveDraft, type DraftFields, type DraftPatch, type SavedDraft } from "../../api/applications";
import { ApiError } from "../../api/errors";

export type SaveState = "idle" | "dirty" | "saving" | "saved" | "conflict" | "error";

export interface Conflict {
  currentDraftRevision: number;
  currentVersion: number;
  serverFields: DraftFields;
  localFields: DraftFields;
  changedKeys: string[];
}

interface Options {
  applicationId: string;
  etag: string;
  draftRevision: number;
  onSaved: (draft: SavedDraft, etag: string) => void;
}

interface Pending {
  fields?: DraftFields;
  declaration_drafts?: DraftPatch["declaration_drafts"];
  attachment_links?: string[];
}

interface ConflictBody {
  current_draft_revision?: number;
  current_version?: number;
  current_fields?: DraftFields;
}

/**
 * Serialised autosave (UI-06 / UI spec s.6): edits settle for 800 ms, then one PATCH runs at a
 * time with the edited draft revision, the application ETag and a per-attempt idempotency key
 * (reused on retry so an ambiguous outcome replays instead of duplicating). A 412 becomes an
 * explicit conflict the user resolves; nothing is overwritten silently.
 */
export function useDraftAutosave({ applicationId, etag, draftRevision, onSaved }: Options) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<SaveState>("idle");
  const [error, setError] = useState<unknown>(null);
  const [conflict, setConflict] = useState<Conflict | null>(null);
  const pending = useRef<Pending | null>(null);
  const inFlight = useRef(false);
  const blocked = useRef(false);
  const timer = useRef<number | null>(null);
  const attemptKey = useRef<string>(crypto.randomUUID());
  const latest = useRef({ etag, draftRevision });

  useEffect(() => {
    latest.current = { etag, draftRevision };
  }, [etag, draftRevision]);

  const takePending = (): Pending | null => {
    const value = pending.current;
    pending.current = null;
    return value;
  };
  const mergePending = (extra: Pending) => {
    const current: Pending = pending.current ?? {};
    pending.current = {
      ...current,
      ...extra,
      fields: extra.fields || current.fields ? { ...(current.fields ?? {}), ...(extra.fields ?? {}) } : undefined,
    };
  };
  const hasPending = (): boolean => pending.current !== null;

  const flush = useCallback(async () => {
    if (inFlight.current || blocked.current) return;
    const taken = takePending();
    if (!taken) return;
    const patch: DraftPatch = { ...taken, draft_revision: latest.current.draftRevision };
    inFlight.current = true;
    setState("saving");
    try {
      const { draft, etag: newEtag } = await saveDraft(applicationId, patch, latest.current.etag, attemptKey.current);
      attemptKey.current = crypto.randomUUID();
      latest.current = { etag: newEtag, draftRevision: draft.draft_revision };
      onSaved(draft, newEtag);
      setError(null);
      setState(hasPending() ? "dirty" : "saved");
      await queryClient.invalidateQueries({ queryKey: ["applications", "list"] });
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 412) {
        const body = (cause.body ?? {}) as ConflictBody;
        const serverFields = body.current_fields ?? {};
        const localFields = patch.fields ?? {};
        setConflict({
          currentDraftRevision: body.current_draft_revision ?? latest.current.draftRevision,
          currentVersion: body.current_version ?? 0,
          serverFields,
          localFields,
          changedKeys: Object.keys(localFields).filter((k) => String(localFields[k] ?? "") !== String(serverFields[k] ?? "")),
        });
        blocked.current = true;
        pending.current = null;
        setState("conflict");
      } else {
        // Keep the same key: a retry of an ambiguous outcome must replay, not duplicate.
        mergePending(taken);
        setError(cause);
        setState("error");
      }
    } finally {
      inFlight.current = false;
      if (hasPending() && !blocked.current) {
        void flush();
      }
    }
  }, [applicationId, onSaved, queryClient]);

  const schedule = useCallback(
    (patch: Pending, delay = 800) => {
      mergePending(patch);
      setState("dirty");
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        timer.current = null;
        void flush();
      }, delay);
    },
    [flush],
  );

  const saveNow = useCallback(() => {
    if (timer.current) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    return flush();
  }, [flush]);

  const retry = useCallback(() => flush(), [flush]);

  const resolveConflict = useCallback(
    (keep: "server" | "mine", fields: DraftFields, newEtag: string, newRevision: number) => {
      latest.current = { etag: newEtag, draftRevision: newRevision };
      setConflict(null);
      blocked.current = false;
      attemptKey.current = crypto.randomUUID();
      if (keep === "mine") {
        pending.current = { fields };
        setState("dirty");
        void flush();
      } else {
        setState("saved");
      }
    },
    [flush],
  );

  // Unsaved-change protection (UI spec s.6 / G-08): while an edit is waiting for the debounce, a
  // save is in flight, or the last save failed with edits still pending, leaving the page would
  // lose typed input - ask the browser to confirm. Once everything is saved the prompt is silent.
  const unsaved = state === "dirty" || state === "saving" || state === "error";
  useEffect(() => {
    if (!unsaved) return undefined;
    const guard = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Legacy browsers read returnValue; the text itself is never shown by modern browsers.
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [unsaved]);

  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
      // In-app navigation away from the wizard: persist what was still waiting for the debounce
      // instead of dropping it (the request completes even though the component is gone).
      if (hasPending() && !inFlight.current && !blocked.current) void flush();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- unmount-only cleanup
    [],
  );

  return { state, error, conflict, schedule, saveNow, retry, resolveConflict };
}
