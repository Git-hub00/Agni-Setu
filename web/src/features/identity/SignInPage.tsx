import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { staffSignInUrl, startOtp, verifyOtp, type Channel, type ChallengeStarted } from "../../api/auth";
import { ApiError, NetworkError } from "../../api/errors";
import { t, type MessageKey } from "../../locales";
import { safeNext } from "./useSession";

const ERROR_KEYS: Partial<Record<string, MessageKey>> = {
  OTP_INVALID: "signIn.error.otpInvalid",
  OTP_EXPIRED: "signIn.error.otpExpired",
  OTP_THROTTLED: "signIn.error.otpThrottled",
  VALIDATION_FAILED: "signIn.error.validation",
  CSRF_FAILED: "signIn.error.csrf",
  DEPENDENCY_UNAVAILABLE: "signIn.error.unavailable",
  forbidden: "signIn.error.staffNotProvisioned",
  authority_revoked: "signIn.error.staffDisabled",
  oidc_failed: "signIn.error.oidcFailed",
};

function describeError(error: unknown): { message: string; requestId: string | null } {
  if (error instanceof ApiError) {
    const key = ERROR_KEYS[error.code ?? ""];
    return { message: key ? t(key) : t("signIn.error.generic"), requestId: error.body?.request_id ?? null };
  }
  if (error instanceof NetworkError) {
    return { message: t("home.apiError"), requestId: null };
  }
  return { message: t("signIn.error.generic"), requestId: null };
}

/** A ticking "now" while a countdown is active; state changes only from the interval callback. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) {
      return;
    }
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);
  return now;
}

function secondsUntil(target: string | null | undefined, now: number): number {
  if (!target) {
    return 0;
  }
  return Math.max(0, Math.ceil((new Date(target).getTime() - now) / 1000));
}

/** UI-02: applicant OTP sign-in and staff OIDC entry. Never asks for a role. */
export function SignInPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const next = safeNext(params.get("next"));
  const redirectError = params.get("error");

  const [channel, setChannel] = useState<Channel>("EMAIL");
  const [contact, setContact] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<ChallengeStarted | null>(null);
  const contactId = useId();
  const codeId = useId();
  const channelId = useId();

  const now = useNow(challenge !== null);
  const expiresIn = secondsUntil(challenge?.expires_at, now);
  const resendIn = secondsUntil(challenge?.resend_available_at, now);

  const start = useMutation({
    mutationFn: () => startOtp(channel, contact.trim()),
    onSuccess: (started) => {
      setChallenge(started);
      setCode("");
    },
  });
  const verify = useMutation({
    mutationFn: () => {
      if (!challenge) throw new Error("no challenge");
      return verifyOtp({ challengeId: challenge.challenge_id, code: code.trim(), channel, contact: contact.trim() });
    },
    onSuccess: async (principal) => {
      // Identity changed: drop every cached scoped read (security s.4) but keep the session
      // query alive - `clear()` would orphan the shell's mounted observer, which then never
      // sees the new principal until a full reload (found by the B16 browser suite).
      await queryClient.cancelQueries();
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== "session" });
      queryClient.setQueryData(["session", "me"], principal);
      await navigate(next, { replace: true });
    },
  });

  const onSend = (event: FormEvent) => {
    event.preventDefault();
    start.mutate();
  };
  const onVerify = (event: FormEvent) => {
    event.preventDefault();
    verify.mutate();
  };
  const reset = () => {
    setChallenge(null);
    setCode("");
    start.reset();
    verify.reset();
  };

  const activeError = verify.error ?? start.error;
  const described = activeError ? describeError(activeError) : null;
  const redirectMessage = redirectError ? t(ERROR_KEYS[redirectError] ?? "signIn.error.generic") : null;

  return (
    <div className="mx-auto grid max-w-4xl gap-6 md:grid-cols-2">
      <section aria-labelledby="applicant-signin" className="rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]">
        <h1 id="applicant-signin" className="text-2xl font-semibold text-ink">{t("signIn.applicant.title")}</h1>
        <p className="mt-1 text-sm text-muted">{t("signIn.applicant.body")}</p>

        {redirectMessage ? (
          <p role="alert" className="mt-4 rounded-md border border-danger bg-danger-soft p-3 text-sm text-danger">{redirectMessage}</p>
        ) : null}

        {!challenge ? (
          <form onSubmit={onSend} className="mt-4 flex flex-col gap-4" aria-busy={start.isPending}>
            <div>
              <label htmlFor={channelId} className="block text-sm font-medium text-ink">{t("signIn.channel")}</label>
              <select id={channelId} value={channel} onChange={(e) => setChannel(e.target.value as Channel)} className="mt-1 min-h-11 w-full rounded-md border border-border bg-surface px-3">
                <option value="EMAIL">{t("signIn.channel.email")}</option>
                <option value="SMS">{t("signIn.channel.sms")}</option>
              </select>
            </div>
            <div>
              <label htmlFor={contactId} className="block text-sm font-medium text-ink">
                {channel === "EMAIL" ? t("signIn.contact.email") : t("signIn.contact.sms")}
              </label>
              <input
                id={contactId}
                type={channel === "EMAIL" ? "email" : "tel"}
                inputMode={channel === "EMAIL" ? "email" : "tel"}
                autoComplete={channel === "EMAIL" ? "email" : "tel"}
                required
                value={contact}
                onChange={(e) => setContact(e.target.value)}
                className="mt-1 min-h-11 w-full rounded-md border border-border bg-surface px-3"
                aria-describedby={`${contactId}-help`}
              />
              <p id={`${contactId}-help`} className="mt-1 text-xs text-muted">{t("signIn.contact.help")}</p>
            </div>
            <button type="submit" disabled={start.isPending || !contact.trim()} className="inline-flex min-h-11 items-center justify-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60">
              {start.isPending ? t("signIn.sending") : t("signIn.sendCode")}
            </button>
          </form>
        ) : (
          <form onSubmit={onVerify} className="mt-4 flex flex-col gap-4" aria-busy={verify.isPending}>
            <p className="text-sm text-ink">
              {t("signIn.codeSentTo")} <span className="font-medium">{challenge.masked_destination}</span>
            </p>
            <p className="text-xs text-muted" aria-live="polite">
              {expiresIn > 0 ? `${t("signIn.expiresIn")} ${expiresIn}s` : t("signIn.expired")}
            </p>
            <div>
              <label htmlFor={codeId} className="block text-sm font-medium text-ink">{t("signIn.code")}</label>
              <input
                id={codeId}
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                required
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                className="mt-1 min-h-11 w-full rounded-md border border-border bg-surface px-3 tracking-widest"
              />
            </div>
            <div className="flex flex-wrap gap-3">
              <button type="submit" disabled={verify.isPending || code.length !== 6 || expiresIn === 0} className="inline-flex min-h-11 items-center justify-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60">
                {verify.isPending ? t("signIn.verifying") : t("signIn.verify")}
              </button>
              <button type="button" onClick={() => start.mutate()} disabled={resendIn > 0 || start.isPending} className="inline-flex min-h-11 items-center rounded-md border border-border px-4 text-ink disabled:opacity-60">
                {resendIn > 0 ? `${t("signIn.resendIn")} ${resendIn}s` : t("signIn.resend")}
              </button>
              <button type="button" onClick={reset} className="inline-flex min-h-11 items-center px-2 text-muted underline">
                {t("signIn.changeContact")}
              </button>
            </div>
          </form>
        )}

        {described ? (
          <p role="alert" className="mt-4 rounded-md border border-danger bg-danger-soft p-3 text-sm text-danger">
            {described.message}
            {described.requestId ? <span className="block text-xs text-muted">{t("signIn.reference")} {described.requestId}</span> : null}
          </p>
        ) : null}
      </section>

      <section aria-labelledby="staff-signin" className="rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]">
        <h2 id="staff-signin" className="text-2xl font-semibold text-ink">{t("signIn.staff.title")}</h2>
        <p className="mt-1 text-sm text-muted">{t("signIn.staff.body")}</p>
        <a href={staffSignInUrl(next)} className="mt-4 inline-flex min-h-11 items-center rounded-md border border-primary px-4 font-medium text-primary hover:bg-primary-soft">
          {t("signIn.staff.button")}
        </a>
      </section>
    </div>
  );
}
