import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { preferencesQuery, updatePreferences, type Preferences } from "../../api/notifications";
import { ProblemNotice } from "../../app/ProblemNotice";
import { useSession } from "../identity/useSession";
import { t } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 py-2 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";

/** UI-27: personal settings only. Language, optional notification channels, reduced motion and
 *  the display time zone; identity and roles are read-only here (they change through UI-21). */
export function SettingsPage() {
  const { principal } = useSession();
  const preferences = useQuery(preferencesQuery);
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-ink">{t("settings.title")}</h1>
        <p className="mt-1 max-w-prose text-sm text-muted">{t("settings.help")}</p>
      </div>
      <section className={CARD} aria-labelledby="settings-identity">
        <h2 id="settings-identity" className="text-base font-semibold">{t("settings.identityTitle")}</h2>
        <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted">{t("settings.name")}</dt>
            <dd>{principal?.display_name ?? "-"}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted">{t("settings.workspaces")}</dt>
            <dd>{principal?.workspaces.join(", ") ?? "-"}</dd>
          </div>
        </dl>
        <p className="mt-2 text-xs text-muted">{t("settings.identityHint")}</p>
      </section>
      {preferences.isPending ? <p className="text-sm text-muted">{t("review.loading")}</p> : null}
      {preferences.isError ? <ProblemNotice error={preferences.error} /> : null}
      {preferences.data ? <PreferencesForm initial={preferences.data} /> : null}
    </div>
  );
}

/** Mounted only once the saved preferences are known, so the form state starts from them. */
function PreferencesForm({ initial }: { initial: Preferences }) {
  const queryClient = useQueryClient();
  const [locale, setLocale] = useState(initial.locale);
  const [channels, setChannels] = useState<string[]>(initial.optional_channels);
  const [reducedMotion, setReducedMotion] = useState(initial.reduced_motion);
  const [timeZone, setTimeZone] = useState(() => window.localStorage.getItem("agni.timezone") ?? "Asia/Kolkata");
  const ids = { locale: useId(), email: useId(), sms: useId(), motion: useId(), tz: useId() };
  const save = useMutation({
    mutationFn: () => updatePreferences({ locale, optional_channels: channels, reduced_motion: reducedMotion }),
    onSuccess: async () => {
      window.localStorage.setItem("agni.timezone", timeZone);
      document.documentElement.dataset.reducedMotion = reducedMotion ? "true" : "false";
      await queryClient.invalidateQueries({ queryKey: ["preferences"] });
    },
  });
  const toggle = (channel: string, on: boolean) => setChannels((current) => (on ? [...new Set([...current, channel])] : current.filter((c) => c !== channel)));
  return (
    <>
      <form
        className={CARD}
        aria-labelledby="settings-preferences"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <h2 id="settings-preferences" className="text-base font-semibold">{t("settings.preferencesTitle")}</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor={ids.locale} className="text-sm font-medium">{t("settings.language")}</label>
            <select id={ids.locale} className={FIELD} value={locale} onChange={(e) => setLocale(e.target.value)}>
              <option value="en">English</option>
              <option value="hi">हिन्दी (Hindi)</option>
              <option value="kn">ಕನ್ನಡ (Kannada)</option>
            </select>
          </div>
          <div>
            <label htmlFor={ids.tz} className="text-sm font-medium">{t("settings.timeZone")}</label>
            <select id={ids.tz} className={FIELD} value={timeZone} onChange={(e) => setTimeZone(e.target.value)}>
              <option value="Asia/Kolkata">Asia/Kolkata (IST)</option>
              <option value="UTC">UTC</option>
            </select>
          </div>
        </div>
        <fieldset className="mt-3">
          <legend className="text-sm font-medium">{t("settings.channels")}</legend>
          <p className="text-xs text-muted">{initial.mandatory_note || t("settings.channelsHint")}</p>
          <div className="mt-2 flex flex-wrap gap-4 text-sm">
            <label htmlFor={ids.email} className="inline-flex min-h-11 items-center gap-2">
              <input id={ids.email} type="checkbox" checked={channels.includes("EMAIL")} onChange={(e) => toggle("EMAIL", e.target.checked)} />
              {t("settings.email")}
            </label>
            <label htmlFor={ids.sms} className="inline-flex min-h-11 items-center gap-2">
              <input id={ids.sms} type="checkbox" checked={channels.includes("SMS")} onChange={(e) => toggle("SMS", e.target.checked)} />
              {t("settings.sms")}
            </label>
          </div>
        </fieldset>
        <label htmlFor={ids.motion} className="mt-3 inline-flex min-h-11 items-center gap-2 text-sm">
          <input id={ids.motion} type="checkbox" checked={reducedMotion} onChange={(e) => setReducedMotion(e.target.checked)} />
          {t("settings.reducedMotion")}
        </label>
        {save.isError ? <ProblemNotice error={save.error} /> : null}
        {save.isSuccess ? <p role="status" className="mt-2 text-sm text-positive">{t("settings.saved")}</p> : null}
        <div className="mt-4">
          <button type="submit" className={BUTTON} disabled={save.isPending}>{t("settings.save")}</button>
        </div>
      </form>
    </>
  );
}
