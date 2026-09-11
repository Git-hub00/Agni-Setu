import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { markRead, notificationsQuery, preferencesQuery, readThrough, updatePreferences, type Notification } from "../../api/notifications";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-4 shadow-[var(--shadow-card)]";
const SECONDARY = "inline-flex min-h-11 items-center rounded-md border border-border bg-surface px-4 font-medium text-ink hover:bg-canvas disabled:opacity-60";

/** UI-19: chronological personal notifications with an unread filter, mark read, mark read
 *  through the visible boundary, delivery status for the account holder and optional
 *  preferences. Read status never changes case state; failed e-mail never removes the
 *  in-app notification. */
export function NotificationsPage() {
  const [params, setParams] = useSearchParams();
  const unreadOnly = params.get("filter") === "unread";
  const queryClient = useQueryClient();
  const query = useQuery(notificationsQuery(unreadOnly));
  const data = query.data;
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["notifications"] });
  };
  const read = useMutation({ mutationFn: (id: string) => markRead(id), onSuccess: refresh });
  const sweep = useMutation({ mutationFn: (through: string) => readThrough(through), onSuccess: refresh });
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-ink">
          {t("notifications.title")} {data ? <span className="ml-2 rounded-md bg-primary-soft px-2 py-0.5 text-sm text-primary">{data.unread_count} {t("notifications.unread")}</span> : null}
        </h1>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" aria-pressed={!unreadOnly} className={`min-h-11 rounded-md px-3 text-sm ${!unreadOnly ? "bg-primary text-white" : "border border-border bg-surface text-ink"}`} onClick={() => setParams({})}>{t("notifications.all")}</button>
          <button type="button" aria-pressed={unreadOnly} className={`min-h-11 rounded-md px-3 text-sm ${unreadOnly ? "bg-primary text-white" : "border border-border bg-surface text-ink"}`} onClick={() => setParams({ filter: "unread" })}>{t("notifications.unreadOnly")}</button>
          {data && data.unread_count > 0 ? (
            <button type="button" className={SECONDARY} disabled={sweep.isPending} onClick={() => sweep.mutate(data.as_of)}>{t("notifications.markAllRead")}</button>
          ) : null}
        </div>
      </div>
      {query.isPending ? <p className="text-sm text-muted">{t("notifications.loading")}</p> : null}
      {query.isError ? <ProblemNotice error={query.error} /> : null}
      {read.isError ? <ProblemNotice error={read.error} /> : null}
      {data && data.items.length === 0 ? <p className="text-sm text-muted">{t("notifications.empty")}</p> : null}
      <ol className="flex flex-col gap-2">
        {(data?.items ?? []).map((n) => (
          <li key={n.notification_id}>
            <NotificationCard notification={n} onRead={() => read.mutate(n.notification_id)} />
          </li>
        ))}
      </ol>
      <PreferencesCard />
    </div>
  );
}

function NotificationCard({ notification: n, onRead }: { notification: Notification; onRead: () => void }) {
  const unread = n.read_at === null;
  return (
    <article className={`${CARD} ${unread ? "border-l-4 border-l-primary" : ""}`} aria-label={n.title}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted">{n.category} · {new Date(n.created_at).toLocaleString()}{n.mandatory ? ` · ${t("notifications.mandatory")}` : ""}</p>
          <h2 className="mt-1 text-base font-semibold text-ink">{n.title}</h2>
          <p className="mt-1 text-sm">{n.body}</p>
          {n.deliveries.length > 0 ? (
            <ul className="mt-2 flex flex-wrap gap-2 text-xs">
              {n.deliveries.map((d) => (
                <li key={d.channel} className={`rounded border px-2 py-0.5 ${d.state === "FAILED" ? "border-warning text-warning" : "border-border text-muted"}`}>
                  {d.channel} · {t(`notifications.delivery.${d.state}` as "notifications.delivery.READY")}{d.destination_masked ? ` · ${d.destination_masked}` : ""}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          {n.target_path ? <Link to={n.target_path} className={SECONDARY}>{t("notifications.open")}</Link> : null}
          {unread ? <button type="button" className={SECONDARY} onClick={onRead}>{t("notifications.markRead")}</button> : <span className="text-xs text-muted">{t("notifications.read")} {n.read_at ? new Date(n.read_at).toLocaleString() : ""}</span>}
        </div>
      </div>
    </article>
  );
}

function PreferencesCard() {
  const queryClient = useQueryClient();
  const prefs = useQuery(preferencesQuery);
  const [email, setEmail] = useState<boolean | null>(null);
  const [reduced, setReduced] = useState<boolean | null>(null);
  const ids = { email: useId(), motion: useId() };
  const save = useMutation({
    mutationFn: () =>
      updatePreferences({
        locale: prefs.data?.locale ?? "en",
        optional_channels: (email ?? prefs.data?.optional_channels.includes("EMAIL") ?? false) ? ["EMAIL"] : [],
        reduced_motion: reduced ?? prefs.data?.reduced_motion ?? false,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["preferences"] });
    },
  });
  if (!prefs.data) return null;
  const emailOn = email ?? prefs.data.optional_channels.includes("EMAIL");
  const reducedOn = reduced ?? prefs.data.reduced_motion;
  return (
    <section className={CARD} aria-labelledby="notification-preferences">
      <h2 id="notification-preferences" className="text-base font-semibold">{t("notifications.preferences")}</h2>
      <p className="mt-1 text-sm text-muted">{prefs.data.mandatory_note}</p>
      <div className="mt-3 flex flex-col gap-2 text-sm">
        <label htmlFor={ids.email} className="inline-flex items-center gap-2">
          <input id={ids.email} type="checkbox" checked={emailOn} onChange={(e) => setEmail(e.target.checked)} /> {t("notifications.optionalEmail")}
        </label>
        <label htmlFor={ids.motion} className="inline-flex items-center gap-2">
          <input id={ids.motion} type="checkbox" checked={reducedOn} onChange={(e) => setReduced(e.target.checked)} /> {t("notifications.reducedMotion")}
        </label>
        {save.isError ? <ProblemNotice error={save.error} /> : null}
        <button type="button" className={SECONDARY} disabled={save.isPending} onClick={() => save.mutate()}>{t("notifications.savePreferences")}</button>
      </div>
    </section>
  );
}
