import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";

import { auditEventQuery, auditEventsQuery, type AuditFilters } from "../../api/audit";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 py-2 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";

/** UI-23: search audit events within scope; safe summaries only; every search is itself
 *  recorded on the reader's audit chain, and the detail shows the integrity check result. */
export function AuditPage() {
  const [filters, setFilters] = useState<AuditFilters>({});
  const [draft, setDraft] = useState<AuditFilters>({});
  const [selected, setSelected] = useState<string | null>(null);
  const list = useQuery(auditEventsQuery(filters));
  const detail = useQuery(auditEventQuery(selected));
  const ids = { entityType: useId(), entityId: useId(), action: useId(), actor: useId(), from: useId(), to: useId() };
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-ink">{t("audit.title")}</h1>
        <p className="mt-1 max-w-prose text-sm text-muted">{t("audit.help")}</p>
      </div>
      <form
        className={`${CARD} grid gap-3 sm:grid-cols-3`}
        aria-label={t("audit.filters")}
        onSubmit={(e) => {
          e.preventDefault();
          setSelected(null);
          setFilters(draft);
        }}
      >
        <div>
          <label htmlFor={ids.entityType} className="text-sm font-medium">{t("audit.entityType")}</label>
          <input id={ids.entityType} className={FIELD} value={draft.entity_type ?? ""} onChange={(e) => setDraft({ ...draft, entity_type: e.target.value || undefined })} />
        </div>
        <div>
          <label htmlFor={ids.entityId} className="text-sm font-medium">{t("audit.entityId")}</label>
          <input id={ids.entityId} className={FIELD} value={draft.entity_id ?? ""} onChange={(e) => setDraft({ ...draft, entity_id: e.target.value || undefined })} />
        </div>
        <div>
          <label htmlFor={ids.action} className="text-sm font-medium">{t("audit.action")}</label>
          <input id={ids.action} className={FIELD} value={draft.action ?? ""} onChange={(e) => setDraft({ ...draft, action: e.target.value || undefined })} />
        </div>
        <div>
          <label htmlFor={ids.actor} className="text-sm font-medium">{t("audit.actor")}</label>
          <input id={ids.actor} className={FIELD} value={draft.actor_id ?? ""} onChange={(e) => setDraft({ ...draft, actor_id: e.target.value || undefined })} />
        </div>
        <div>
          <label htmlFor={ids.from} className="text-sm font-medium">{t("audit.from")}</label>
          <input id={ids.from} type="datetime-local" className={FIELD} onChange={(e) => setDraft({ ...draft, from: e.target.value ? new Date(e.target.value).toISOString() : undefined })} />
        </div>
        <div>
          <label htmlFor={ids.to} className="text-sm font-medium">{t("audit.to")}</label>
          <input id={ids.to} type="datetime-local" className={FIELD} onChange={(e) => setDraft({ ...draft, to: e.target.value ? new Date(e.target.value).toISOString() : undefined })} />
        </div>
        <div className="sm:col-span-3">
          <button type="submit" className={BUTTON}>{t("audit.search")}</button>
        </div>
      </form>
      {list.isPending ? <p className="text-sm text-muted">{t("audit.loading")}</p> : null}
      {list.isError ? <ProblemNotice error={list.error} /> : null}
      {list.data ? (
        // [&>*]:min-w-0: grid children default to min-width:auto, so the nowrap results table
        // widened the page at 360 px instead of scrolling inside its card (journeys.spec, B19).
        <div className="grid gap-6 lg:grid-cols-[3fr_2fr] [&>*]:min-w-0">
          <section className={`${CARD} overflow-x-auto`} aria-labelledby="audit-results">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 id="audit-results" className="text-base font-semibold">{t("audit.results")}</h2>
              <p className="text-xs text-muted">
                {list.data.redacted ? t("audit.redacted") : t("audit.unredacted")} · {t("audit.searchAudited")}
              </p>
            </div>
            <table className="mt-3 w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-muted">
                  <th className="py-1">{t("audit.when")}</th>
                  <th className="py-1">{t("audit.action")}</th>
                  <th className="py-1">{t("audit.entity")}</th>
                  <th className="py-1">{t("audit.actor")}</th>
                  <th className="py-1"><span className="sr-only">{t("audit.open")}</span></th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((event) => (
                  <tr key={event.audit_event_id} className="border-t border-border align-top">
                    <td className="py-1 whitespace-nowrap">{new Date(event.timestamp).toLocaleString()}</td>
                    <td className="py-1 font-medium">{event.action}</td>
                    <td className="py-1">
                      {event.entity_type}
                      <span className="block text-xs text-muted">{event.entity_id.slice(0, 8)}</span>
                    </td>
                    <td className="py-1 text-xs text-muted">{event.actor_id ? event.actor_id.slice(0, 8) : t("audit.system")}</td>
                    <td className="py-1">
                      <button type="button" className="min-h-11 rounded-md border border-border px-3 text-sm" aria-pressed={selected === event.audit_event_id} onClick={() => setSelected(event.audit_event_id)}>
                        {t("audit.open")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {list.data.items.length === 0 ? <p className="mt-2 text-sm text-muted">{t("audit.empty")}</p> : null}
            {list.data.has_more ? <p className="mt-2 text-xs text-muted">{t("audit.hasMore")}</p> : null}
            <p className="mt-3 text-xs text-muted">{list.data.notice}</p>
          </section>
          <aside className={CARD} aria-live="polite">
            <h2 className="text-base font-semibold">{t("audit.detail")}</h2>
            {selected === null ? <p className="mt-2 text-sm text-muted">{t("audit.selectRow")}</p> : null}
            {detail.isError ? <ProblemNotice error={detail.error} /> : null}
            {detail.data ? (
              <dl className="mt-3 grid gap-2 text-sm">
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted">{t("audit.integrity")}</dt>
                  <dd className={detail.data.integrity.chain_valid ? "font-medium text-positive" : "font-medium text-danger"}>{detail.data.integrity.label}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted">{t("audit.action")}</dt>
                  <dd>{detail.data.action}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted">{t("audit.entity")}</dt>
                  <dd className="break-all">{detail.data.entity_type} · {detail.data.entity_id}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted">{t("audit.requestId")}</dt>
                  <dd className="break-all">{detail.data.request_id}</dd>
                </div>
                {detail.data.authority_grant_id ? (
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-muted">{t("audit.grant")}</dt>
                    <dd className="break-all">{detail.data.authority_grant_id}</dd>
                  </div>
                ) : null}
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted">{t("audit.summary")}</dt>
                  <dd>
                    <pre className="overflow-x-auto rounded-md bg-canvas p-2 text-xs">{JSON.stringify(detail.data.summary, null, 2)}</pre>
                  </dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted">{t("audit.hash")}</dt>
                  <dd className="break-all text-xs">{detail.data.hash}</dd>
                </div>
              </dl>
            ) : null}
          </aside>
        </div>
      ) : null}
    </div>
  );
}
