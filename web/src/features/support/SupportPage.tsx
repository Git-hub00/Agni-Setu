import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link, useNavigate } from "react-router";

import { applicationsQuery } from "../../api/applications";
import { TICKET_CATEGORIES, createTicket, ticketsQuery, type TicketCategory } from "../../api/support";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t, type MessageKey } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 py-2 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";

const CATEGORY_LABEL: Record<TicketCategory, MessageKey> = {
  HOW_TO: "support.category.HOW_TO",
  TECHNICAL: "support.category.TECHNICAL",
  ACCESS: "support.category.ACCESS",
  DATA_CORRECTION: "support.category.DATA_CORRECTION",
  OTHER: "support.category.OTHER",
};

export function stateTone(state: string): string {
  if (state === "RESOLVED" || state === "CLOSED") return "bg-positive-soft text-positive";
  if (state === "WAITING_FOR_REQUESTER") return "bg-warning-soft text-warning";
  return "bg-information-soft text-information";
}

/** UI-26: help, tickets and the referral for routes the profile does not enable. A ticket is
 *  not an emergency channel or a legal appeal; withdrawal stays on the case page. */
export function SupportPage() {
  const query = useQuery(ticketsQuery());
  const cases = useQuery(applicationsQuery({}));
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [category, setCategory] = useState<TicketCategory>("HOW_TO");
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [applicationId, setApplicationId] = useState("");
  const ids = { category: useId(), subject: useId(), description: useId(), application: useId() };
  const create = useMutation({
    mutationFn: () => createTicket({ category, subject: subject.trim(), description: description.trim(), ...(applicationId ? { application_id: applicationId } : {}) }),
    onSuccess: async (ticket) => {
      await queryClient.invalidateQueries({ queryKey: ["tickets"] });
      await navigate(`/support/${ticket.ticket_id}`);
    },
  });
  if (query.isPending) return <p className="text-sm text-muted">{t("review.loading")}</p>;
  if (query.isError) return <ProblemNotice error={query.error} />;
  const { items, routes, support_scope } = query.data;
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-ink">{t("support.title")}</h1>
        <p className="mt-1 max-w-prose text-sm text-muted">{t("support.help")}</p>
      </div>
      <section className={CARD} aria-labelledby="support-routes">
        <h2 id="support-routes" className="text-base font-semibold">{t("support.routesTitle")}</h2>
        <ul className="mt-2 flex flex-col gap-1 text-sm">
          <li>
            <span className="font-medium">{t("support.appeals")}:</span>{" "}
            {routes.appeals.enabled ? t("support.enabled") : `${t("support.notEnabled")} ${routes.appeals.referral_text}`}
          </li>
          <li><span className="font-medium">{t("support.fees")}:</span> {routes.fees.enabled ? t("support.enabled") : t("support.notEnabled")}</li>
          <li><span className="font-medium">{t("support.externalRegistration")}:</span> {routes.external_registration.enabled ? t("support.enabled") : t("support.notEnabled")}</li>
          <li><span className="font-medium">{t("support.declarations")}:</span> {routes.continuing_declarations.enabled ? t("support.enabled") : t("support.notEnabled")}</li>
        </ul>
        <p className="mt-2 text-xs text-muted">{t("support.routesHint")}</p>
      </section>
      <section className={CARD} aria-labelledby="support-new">
        <h2 id="support-new" className="text-base font-semibold">{t("support.newTitle")}</h2>
        <form className="mt-3 flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor={ids.category} className="text-sm font-medium">{t("support.categoryLabel")}</label>
              <select id={ids.category} className={FIELD} value={category} onChange={(e) => setCategory(e.target.value as TicketCategory)}>
                {TICKET_CATEGORIES.map((c) => <option key={c} value={c}>{t(CATEGORY_LABEL[c])}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor={ids.application} className="text-sm font-medium">{t("support.caseLabel")}</label>
              <select id={ids.application} className={FIELD} value={applicationId} onChange={(e) => setApplicationId(e.target.value)}>
                <option value="">{t("support.noCase")}</option>
                {(cases.data?.items ?? []).map((c) => (
                  <option key={c.application_id} value={c.application_id}>{c.public_reference ?? c.draft_reference} · {c.premises.display_name}</option>
                ))}
              </select>
            </div>
          </div>
          <label htmlFor={ids.subject} className="text-sm font-medium">{t("support.subject")}</label>
          <input id={ids.subject} className={FIELD} minLength={5} maxLength={160} value={subject} onChange={(e) => setSubject(e.target.value)} />
          <label htmlFor={ids.description} className="text-sm font-medium">{t("support.description")}</label>
          <textarea id={ids.description} className={FIELD} rows={4} minLength={10} maxLength={4000} value={description} onChange={(e) => setDescription(e.target.value)} />
          {create.isError ? <ProblemNotice error={create.error} /> : null}
          <button type="submit" className={BUTTON} disabled={create.isPending || subject.trim().length < 5 || description.trim().length < 10}>
            {t("support.create")}
          </button>
        </form>
      </section>
      <section className={CARD} aria-labelledby="support-list">
        <h2 id="support-list" className="text-base font-semibold">{support_scope ? t("support.queueTitle") : t("support.mineTitle")}</h2>
        {items.length === 0 ? <p className="mt-2 text-sm text-muted">{t("support.empty")}</p> : null}
        <ul className="mt-3 flex flex-col gap-2 text-sm">
          {items.map((ticket) => (
            <li key={ticket.ticket_id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border p-3">
              <div>
                <p className="font-medium">{ticket.subject}</p>
                <p className="text-muted">
                  {t(CATEGORY_LABEL[ticket.category])}{ticket.public_reference ? ` · ${ticket.public_reference}` : ""} · {new Date(ticket.updated_at).toLocaleString()}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${stateTone(ticket.state)}`}>{ticket.state}</span>
                <Link to={`/support/${ticket.ticket_id}`} className="inline-flex min-h-11 items-center rounded-md border border-border px-3 font-medium text-ink">{t("support.open")}</Link>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
