import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { publicVerificationQuery, type EffectiveStatus, type PublicVerification } from "../../api/certificates";
import { ApiError, NetworkError } from "../../api/errors";
import { t, type MessageKey } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const STATUS_LABEL: Record<EffectiveStatus, MessageKey> = {
  ACTIVE: "verify.status.ACTIVE",
  EXPIRED: "verify.status.EXPIRED",
  SUSPENDED: "verify.status.SUSPENDED",
  REVOKED: "verify.status.REVOKED",
  SUPERSEDED: "verify.status.SUPERSEDED",
};

/** UI-18: public verification. ACTIVE is green only with a fresh authoritative answer; unknown
 *  shows "Record not found" without hints; an outage shows "Unable to verify now" in amber and
 *  is never rendered as ACTIVE. Results are never cached. */
export function VerifyPage() {
  const { token = "" } = useParams();
  const navigate = useNavigate();
  const [value, setValue] = useState(token);
  const inputId = useId();
  const query = useQuery({ ...publicVerificationQuery(token), enabled: token.length > 0 });
  const submit = () => {
    const trimmed = value.trim();
    if (trimmed) void navigate(`/verify/${encodeURIComponent(trimmed)}`);
  };
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-ink">{t("verify.title")}</h1>
        <p className="mt-1 max-w-prose text-sm text-muted">{t("verify.help")}</p>
      </div>
      <form className={`${CARD} flex flex-wrap items-end gap-3`} onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <label htmlFor={inputId} className="flex min-w-72 flex-1 flex-col text-sm">
          <span className="font-medium">{t("verify.input")}</span>
          <input id={inputId} className="mt-1 min-h-11 rounded-md border border-border bg-canvas px-3 text-sm" value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" spellCheck={false} />
        </label>
        <button type="submit" className="inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white" disabled={value.trim().length === 0}>{t("verify.submit")}</button>
        <p className="w-full text-xs text-muted">{t("verify.scanHint")}</p>
      </form>
      {token ? <Result state={query} onRetry={() => void query.refetch()} /> : null}
      <p className="text-xs text-muted">{t("verify.privacy")}</p>
    </div>
  );
}

function Result({ state, onRetry }: { state: UseQueryResult<PublicVerification>; onRetry: () => void }) {
  if (state.isPending) return <p role="status" className="text-sm text-muted">{t("verify.checking")}</p>;
  if (state.isError) {
    const error = state.error;
    if (error instanceof ApiError && error.status === 404) {
      return (
        <section role="status" className={`${CARD} border-border`} aria-labelledby="verify-result">
          <h2 id="verify-result" className="text-base font-semibold">{t("verify.notFound")}</h2>
          <p className="mt-1 text-sm text-muted">{t("verify.notFoundHint")}</p>
        </section>
      );
    }
    if (error instanceof ApiError && error.status === 429) {
      return <p role="status" className="rounded-md bg-warning-soft p-3 text-sm text-warning">{t("verify.tooMany")}</p>;
    }
    const outage = error instanceof NetworkError || (error instanceof ApiError && error.status >= 500);
    return (
      <section role="status" className={`${CARD} border-warning bg-warning-soft`} aria-labelledby="verify-result">
        <h2 id="verify-result" className="text-base font-semibold text-warning">{t("verify.unavailable")}</h2>
        <p className="mt-1 text-sm text-ink">{outage ? t("verify.unavailableHint") : error.message}</p>
        <button type="button" className="mt-3 inline-flex min-h-11 items-center rounded-md border border-border bg-surface px-4 text-sm font-medium" onClick={onRetry}>{t("verify.retry")}</button>
      </section>
    );
  }
  const result = state.data;
  const active = result.effective_status === "ACTIVE";
  const tone = active ? "border-positive bg-positive-soft" : result.effective_status === "REVOKED" ? "border-danger bg-danger-soft" : "border-warning bg-warning-soft";
  return (
    <section role="status" className={`${CARD} ${tone}`} aria-labelledby="verify-result">
      <h2 id="verify-result" className="text-base font-semibold">{t("verify.result")}: {t(STATUS_LABEL[result.effective_status])}</h2>
      {result.is_demo ? <p className="mt-1 inline-block rounded-md bg-surface px-2 py-0.5 text-xs font-medium text-warning">{t("verify.demoNotice")}</p> : null}
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
        <dt className="text-muted">{t("certificates.number")}</dt><dd>{result.certificate_number}</dd>
        <dt className="text-muted">{t("verify.premises")}</dt><dd>{result.premises_display_name} · {result.locality}</dd>
        <dt className="text-muted">{t("verify.issued")}</dt><dd>{new Date(result.issued_at).toLocaleDateString()}</dd>
        <dt className="text-muted">{t("verify.validUntil")}</dt><dd>{result.valid_until ? new Date(result.valid_until).toLocaleDateString() : "-"}</dd>
        <dt className="text-muted">{t("verify.issuer")}</dt><dd>{result.issuer_label} · {result.source}</dd>
        <dt className="text-muted">{t("verify.checkedAt")}</dt><dd>{new Date(result.checked_at).toLocaleString()}</dd>
      </dl>
    </section>
  );
}
