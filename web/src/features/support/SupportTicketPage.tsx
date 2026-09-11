import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link, useParams } from "react-router";

import { uploadFile } from "../../api/applications";
import { TICKET_STATES, addTicketMessage, changeTicketStatus, ticketQuery, type TicketState } from "../../api/support";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";
import { stateTone } from "./SupportPage";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 py-2 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";
const SECONDARY = "inline-flex min-h-11 items-center rounded-md border border-border bg-surface px-4 font-medium text-ink hover:bg-canvas disabled:opacity-60";

/** UI-26 ticket: audience-filtered conversation (requesters never see INTERNAL notes), a reply
 *  form with scanned attachments, and the support status actions the server permits. */
export function SupportTicketPage() {
  const { ticketId = "" } = useParams();
  const query = useQuery(ticketQuery(ticketId));
  const queryClient = useQueryClient();
  const [body, setBody] = useState("");
  const [internal, setInternal] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [reason, setReason] = useState("");
  const ids = { body: useId(), internal: useId(), file: useId(), reason: useId() };
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["tickets"] });
  };
  const reply = useMutation({
    mutationFn: async () => {
      if (!query.data) throw new Error("ticket not loaded");
      const attachments: string[] = [];
      if (file) {
        const version = await uploadFile("SUPPORT_ATTACHMENT", ticketId, "support-attachment", file);
        attachments.push(version.document_version_id);
      }
      return addTicketMessage(ticketId, { body: body.trim(), audience: internal ? "INTERNAL" : "REQUESTER", ...(attachments.length ? { document_version_ids: attachments } : {}) }, query.data.etag);
    },
    onSuccess: async () => {
      setBody("");
      setFile(null);
      await refresh();
    },
  });
  const status = useMutation({
    mutationFn: (state: TicketState) => {
      if (!query.data) throw new Error("ticket not loaded");
      return changeTicketStatus(ticketId, { state, reason: reason.trim() }, query.data.etag);
    },
    onSuccess: async () => {
      setReason("");
      await refresh();
    },
  });
  if (query.isPending) return <p className="text-sm text-muted">{t("review.loading")}</p>;
  if (query.isError) return <ProblemNotice error={query.error} />;
  const { ticket } = query.data;
  const actions = new Map(ticket.allowed_actions.map((a) => [a.key, a] as const));
  const canReply = actions.get("reply")?.enabled === true;
  const canNote = actions.get("internal-note")?.enabled === true;
  const statusTargets = TICKET_STATES.filter((s) => actions.get(`status:${s}`)?.enabled === true);
  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link to="/support" className="text-sm text-primary">← {t("support.title")}</Link>
        <h1 className="mt-1 text-2xl font-semibold text-ink">{ticket.subject}</h1>
        <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
          <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${stateTone(ticket.state)}`}>{ticket.state}</span>
          <span>{ticket.category}</span>
          {ticket.application_id ? <Link to={`/applications/${ticket.application_id}`} className="text-primary">{ticket.public_reference ?? t("review.viewCase")}</Link> : null}
          <span>· {ticket.owner_queue}</span>
        </p>
        <p className="mt-1 text-xs text-muted">{ticket.notice}</p>
      </div>
      <section className={CARD} aria-labelledby="ticket-conversation">
        <h2 id="ticket-conversation" className="text-base font-semibold">{t("support.conversation")}</h2>
        <ol className="mt-3 flex flex-col gap-3">
          {ticket.messages.map((m) => (
            <li key={m.message_id} className={`rounded-md border p-3 text-sm ${m.audience === "INTERNAL" ? "border-warning bg-warning-soft" : "border-border"} ${m.kind === "STATUS" ? "italic text-muted" : ""}`}>
              <p className="text-xs text-muted">
                {new Date(m.created_at).toLocaleString()} · {m.kind === "STATUS" ? t("support.statusEntry") : m.audience === "INTERNAL" ? t("support.internalNote") : t("support.message")}
              </p>
              <p className="mt-1 whitespace-pre-wrap">{m.body}</p>
              {m.document_version_ids.length > 0 ? <p className="mt-1 text-xs text-muted">{t("support.attachments")}: {m.document_version_ids.length}</p> : null}
            </li>
          ))}
        </ol>
      </section>
      {canReply ? (
        <section className={CARD} aria-labelledby="ticket-reply">
          <h2 id="ticket-reply" className="text-base font-semibold">{t("support.reply")}</h2>
          <form className="mt-3 flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); reply.mutate(); }}>
            <label htmlFor={ids.body} className="text-sm font-medium">{t("support.message")}</label>
            <textarea id={ids.body} className={FIELD} rows={3} maxLength={4000} value={body} onChange={(e) => setBody(e.target.value)} />
            <label htmlFor={ids.file} className="text-sm font-medium">{t("support.attach")}</label>
            <input id={ids.file} type="file" accept="application/pdf,image/jpeg,image/png" className="text-sm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            {canNote ? (
              <label className="flex min-h-11 items-center gap-2 text-sm">
                <input id={ids.internal} type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} /> {t("support.internalNote")}
              </label>
            ) : null}
            {reply.isError ? <ProblemNotice error={reply.error} /> : null}
            <button type="submit" className={BUTTON} disabled={reply.isPending || body.trim().length === 0}>{reply.isPending ? t("submit.working") : t("support.send")}</button>
          </form>
        </section>
      ) : (
        <p role="status" className="text-sm text-muted">{t("support.closedHint")}</p>
      )}
      {statusTargets.length > 0 ? (
        <section className={CARD} aria-labelledby="ticket-status">
          <h2 id="ticket-status" className="text-base font-semibold">{ticket.support_scope ? t("support.statusTitle") : t("support.reopenTitle")}</h2>
          <label htmlFor={ids.reason} className="mt-2 block text-sm font-medium">{t("lifecycle.reason")}</label>
          <textarea id={ids.reason} className={FIELD} rows={2} minLength={10} maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} />
          {status.isError ? <div className="mt-2"><ProblemNotice error={status.error} /></div> : null}
          <div className="mt-3 flex flex-wrap gap-3">
            {statusTargets.map((s) => (
              <button key={s} type="button" className={SECONDARY} disabled={status.isPending || reason.trim().length < 10} onClick={() => status.mutate(s)}>
                {t(`support.state.${s}`)}
              </button>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
