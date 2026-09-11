import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";

import { applicationQuery, type CaseDetail } from "../../api/applications";
import { submitApplication, type SubmissionReceipt } from "../../api/cases";
import { ApiError, NetworkError } from "../../api/errors";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";

const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";
const SECONDARY = "inline-flex min-h-11 items-center rounded-md border border-border bg-surface px-4 font-medium text-ink hover:bg-canvas disabled:opacity-60";

/** UI-06 step 4: explicit confirmation, one stable idempotency key per submission attempt
 *  series, and an "outcome not confirmed" state after a timeout (never a red Failed) that offers
 *  Check status / Retry safely with the same key. */
export function SubmitPanel({ detail, etag, enabled, docIds }: { detail: CaseDetail; etag: string; enabled: boolean; docIds: string[] }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [key] = useState(() => crypto.randomUUID());
  const [unknownOutcome, setUnknownOutcome] = useState(false);
  const draft = detail.draft;

  const submit = useMutation({
    mutationFn: () => {
      if (!draft || !detail.policy.policy_version_id) throw new Error("draft not loaded");
      return submitApplication(
        detail.application_id,
        {
          draft_revision: draft.draft_revision,
          reviewed_policy_version_id: detail.policy.policy_version_id,
          declaration_acceptances: draft.declarations.map((d) => ({ code: d.code, version: d.version, accepted: true as const })),
          document_version_ids: docIds,
        },
        etag,
        key,
      );
    },
    onSuccess: async ({ receipt }) => {
      setUnknownOutcome(false);
      await queryClient.invalidateQueries({ queryKey: ["applications"] });
      await navigate(`/applications/${receipt.application_id}?receipt=${encodeURIComponent(receipt.public_reference)}`, { replace: true });
    },
    onError: (error) => {
      if (error instanceof NetworkError) setUnknownOutcome(true);
    },
  });

  const check = async () => {
    const fresh = await queryClient.fetchQuery(applicationQuery(detail.application_id));
    if (fresh.detail.status !== "DRAFT") {
      await navigate(`/applications/${detail.application_id}`, { replace: true });
    } else {
      setUnknownOutcome(false);
    }
  };

  if (unknownOutcome) {
    return (
      <div role="alert" className="rounded-md border border-warning bg-warning-soft p-4 text-sm">
        <p className="font-medium text-warning">{t("submit.unknown.title")}</p>
        <p className="mt-1 text-ink">{t("submit.unknown.body")}</p>
        <div className="mt-3 flex gap-3">
          <button type="button" className={SECONDARY} onClick={() => void check()}>{t("submit.unknown.check")}</button>
          <button type="button" className={BUTTON} disabled={submit.isPending} onClick={() => submit.mutate()}>{t("submit.unknown.retry")}</button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {submit.isError && !(submit.error instanceof NetworkError) ? <ProblemNotice error={submit.error} /> : null}
      {submit.isError && submit.error instanceof ApiError && submit.error.status === 412 ? (
        <p className="text-sm text-muted">{t("submit.staleHint")}</p>
      ) : null}
      {!confirming ? (
        <button type="button" className={BUTTON} disabled={!enabled || submit.isPending} onClick={() => setConfirming(true)}>
          {t("submit.button")}
        </button>
      ) : (
        <div className="rounded-md border border-border bg-canvas p-4 text-sm">
          <p className="font-medium">{t("submit.confirm.title")}</p>
          <p className="mt-1 text-muted">{t("submit.confirm.body")}</p>
          <div className="mt-3 flex gap-3">
            <button type="button" className={SECONDARY} disabled={submit.isPending} onClick={() => setConfirming(false)}>{t("submit.confirm.cancel")}</button>
            <button type="button" className={BUTTON} disabled={submit.isPending} onClick={() => submit.mutate()}>
              {submit.isPending ? t("submit.working") : t("submit.confirm.yes")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function ReceiptBanner({ receipt }: { receipt: SubmissionReceipt }) {
  return (
    <div role="status" className="rounded-md border border-positive bg-positive-soft p-4 text-sm text-positive">
      <p className="font-medium">{t("receipt.title")} {receipt.public_reference}</p>
      <p>{t("receipt.body")} {new Date(receipt.accepted_at).toLocaleString()} · {receipt.owner_queue.display_name}</p>
    </div>
  );
}
