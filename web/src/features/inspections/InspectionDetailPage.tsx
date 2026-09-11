import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link, useParams } from "react-router";

import {
  cancelInspection,
  checkIn,
  FAILED_VISIT_REASONS,
  failVisit,
  inspectionQuery,
  officersQuery,
  reassignInspection,
  scheduleInspection,
  type InspectionDetail,
} from "../../api/inspections";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";
const SECONDARY = "inline-flex min-h-11 items-center rounded-md border border-border bg-surface px-4 font-medium text-ink hover:bg-canvas disabled:opacity-60";

/** UI-12 (B07 slice) + UI-11 dialog: attempt summary, assignment history, checklist preview,
 *  supervisor scheduling/reassignment/cancellation and the assigned officer's check-in and
 *  failed-visit actions. The report itself arrives with B08. */
export function InspectionDetailPage() {
  const { inspectionId = "" } = useParams();
  const query = useQuery(inspectionQuery(inspectionId));
  if (query.isPending) return <p className="text-sm text-muted">{t("queue.loading")}</p>;
  if (query.isError) return <ProblemNotice error={query.error} />;
  const { inspection, etag } = query.data;
  const actions = new Map(inspection.allowed_actions.map((a) => [a.key, a.enabled] as const));
  return (
    <div className="mx-auto flex max-w-[920px] flex-col gap-6">
      <div>
        <Link to="/inspections" className="text-sm text-primary">← {t("queue.title")}</Link>
        <h1 className="mt-1 text-2xl font-semibold text-ink">
          {inspection.public_reference ?? inspection.application_id.slice(0, 8)} · {t("queue.attempt")} {inspection.attempt_number} · {inspection.status}
        </h1>
        <p className="text-sm text-muted">{inspection.premises.display_name} · {inspection.premises.locality} · {inspection.purpose}</p>
      </div>
      <section className={CARD} aria-labelledby="inspection-summary">
        <h2 id="inspection-summary" className="text-base font-semibold">{t("inspection.summary")}</h2>
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-muted">{t("queue.appointment")}</dt>
          <dd>{inspection.scheduled_start ? `${new Date(inspection.scheduled_start).toLocaleString()} – ${inspection.scheduled_end ? new Date(inspection.scheduled_end).toLocaleTimeString() : ""} (${inspection.appointment_timezone})` : t("queue.notScheduled")}</dd>
          <dt className="text-muted">{t("queue.assignment")}</dt>
          <dd>{inspection.current_assignment ? `${inspection.current_assignment.officer_name} · v${inspection.current_assignment.number} (${inspection.current_assignment.state})` : t("queue.unassignedLabel")}</dd>
          <dt className="text-muted">{t("queue.checklist")}</dt>
          <dd>{inspection.checklist_ref} · {inspection.checklist_items.length} {t("inspection.items")}</dd>
          <dt className="text-muted">{t("inspection.case")}</dt>
          <dd><Link to={`/applications/${inspection.application_id}`} className="text-primary">{inspection.public_reference}</Link> · {inspection.application_status}</dd>
          {inspection.failed_reason_code ? (
            <>
              <dt className="text-muted">{t("inspection.failedReason")}</dt>
              <dd>{inspection.failed_reason_code} · {inspection.failed_notes}</dd>
            </>
          ) : null}
        </dl>
        {inspection.assignments.length > 0 ? (
          <>
            <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-muted">{t("inspection.history")}</h3>
            <ul className="mt-1 text-sm">
              {inspection.assignments.map((a) => (
                <li key={a.assignment_id}>v{a.number} · {a.officer_name} · {a.state} · {a.booking_start ? new Date(a.booking_start).toLocaleString() : "-"}</li>
              ))}
            </ul>
          </>
        ) : null}
      </section>
      {actions.get("schedule") || actions.get("reassign") || actions.get("cancel") ? (
        <SupervisorDialog inspection={inspection} etag={etag} canSchedule={actions.get("schedule") === true} canReassign={actions.get("reassign") === true} canCancel={actions.get("cancel") === true} />
      ) : null}
      {actions.get("check-in") || actions.get("fail-visit") ? (
        <OfficerActions inspection={inspection} etag={etag} canCheckIn={actions.get("check-in") === true} canFail={actions.get("fail-visit") === true} />
      ) : null}
      <section className={CARD} aria-labelledby="inspection-checklist">
        <h2 id="inspection-checklist" className="text-base font-semibold">{t("inspection.checklistPreview")}</h2>
        <p className="mt-1 text-sm text-muted">{t("inspection.reportLater")}</p>
        <ol className="mt-3 flex flex-col gap-1 text-sm">
          {inspection.checklist_items.map((item) => (
            <li key={item.code}>
              <span className="font-medium">{item.code}</span> {item.title} {item.mandatory ? <span className="text-danger">*</span> : null}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function SupervisorDialog({ inspection, etag, canSchedule, canReassign, canCancel }: { inspection: InspectionDetail; etag: string; canSchedule: boolean; canReassign: boolean; canCancel: boolean }) {
  const queryClient = useQueryClient();
  const officers = useQuery(officersQuery);
  const [officer, setOfficer] = useState(inspection.current_assignment?.officer_id ?? "");
  const [start, setStart] = useState(inspection.scheduled_start ? inspection.scheduled_start.slice(0, 16) : "");
  const [end, setEnd] = useState(inspection.scheduled_end ? inspection.scheduled_end.slice(0, 16) : "");
  const [reason, setReason] = useState("");
  const ids = { officer: useId(), start: useId(), end: useId(), reason: useId() };
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["inspections"] });
    await queryClient.invalidateQueries({ queryKey: ["schedule"] });
    await queryClient.invalidateQueries({ queryKey: ["applications"] });
  };
  const toIso = (local: string) => new Date(local).toISOString();
  const schedule = useMutation({ mutationFn: () => scheduleInspection(inspection, { officer_id: officer, starts_at: toIso(start), ends_at: toIso(end), reason }, etag), onSuccess: refresh });
  const reassign = useMutation({ mutationFn: () => reassignInspection(inspection, { new_officer_id: officer, reason }, etag), onSuccess: refresh });
  const cancel = useMutation({ mutationFn: () => cancelInspection(inspection, reason, etag), onSuccess: refresh });
  const error = schedule.error ?? reassign.error ?? cancel.error;
  const valid = reason.trim().length >= 10;
  return (
    <section className={CARD} aria-labelledby="inspection-schedule">
      <h2 id="inspection-schedule" className="text-base font-semibold">{t("inspection.scheduling")}</h2>
      <p className="mt-1 text-sm text-muted">{t("inspection.schedulingHelp")}</p>
      <form className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={(e) => e.preventDefault()}>
        <div>
          <label htmlFor={ids.officer} className="text-sm font-medium">{t("schedule.officer")}</label>
          <select id={ids.officer} className={FIELD} value={officer} onChange={(e) => setOfficer(e.target.value)}>
            <option value="">{t("inspection.chooseOfficer")}</option>
            {(officers.data ?? []).map((o) => (
              <option key={o.officer_id} value={o.officer_id}>{o.display_name}</option>
            ))}
          </select>
        </div>
        <div />
        <div>
          <label htmlFor={ids.start} className="text-sm font-medium">{t("inspection.start")}</label>
          <input id={ids.start} type="datetime-local" className={FIELD} value={start} onChange={(e) => setStart(e.target.value)} />
        </div>
        <div>
          <label htmlFor={ids.end} className="text-sm font-medium">{t("inspection.end")}</label>
          <input id={ids.end} type="datetime-local" className={FIELD} value={end} onChange={(e) => setEnd(e.target.value)} />
        </div>
        <div className="sm:col-span-2">
          <label htmlFor={ids.reason} className="text-sm font-medium">{t("policy.reason")}</label>
          <textarea id={ids.reason} className={FIELD} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} minLength={10} />
        </div>
        {error ? <div className="sm:col-span-2"><ProblemNotice error={error} /></div> : null}
        <div className="flex flex-wrap gap-3 sm:col-span-2">
          {canSchedule ? (
            <button type="button" className={BUTTON} disabled={!valid || !officer || !start || !end || schedule.isPending} onClick={() => schedule.mutate()}>
              {inspection.status === "SCHEDULED" ? t("inspection.reschedule") : t("inspection.schedule")}
            </button>
          ) : null}
          {canReassign ? (
            <button type="button" className={SECONDARY} disabled={!valid || !officer || reassign.isPending} onClick={() => reassign.mutate()}>{t("inspection.reassign")}</button>
          ) : null}
          {canCancel ? (
            <button type="button" className={SECONDARY} disabled={!valid || cancel.isPending} onClick={() => cancel.mutate()}>{t("inspection.cancel")}</button>
          ) : null}
        </div>
      </form>
    </section>
  );
}

function OfficerActions({ inspection, etag, canCheckIn, canFail }: { inspection: InspectionDetail; etag: string; canCheckIn: boolean; canFail: boolean }) {
  const queryClient = useQueryClient();
  const [locationReason, setLocationReason] = useState("");
  const [failReason, setFailReason] = useState("");
  const [failCode, setFailCode] = useState<string>(FAILED_VISIT_REASONS[0]);
  const ids = { location: useId(), code: useId(), reason: useId() };
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["inspections"] });
    await queryClient.invalidateQueries({ queryKey: ["applications"] });
  };
  const arrive = useMutation({
    mutationFn: async () => {
      // Location is optional: a denied GPS needs an explicit reason, never fabricated coordinates.
      const position = await new Promise<GeolocationPosition | null>((resolve) => {
        if (!("geolocation" in navigator)) return resolve(null);
        navigator.geolocation.getCurrentPosition((p) => resolve(p), () => resolve(null), { timeout: 5000 });
      });
      return checkIn(
        inspection,
        position
          ? { latitude: position.coords.latitude, longitude: position.coords.longitude, accuracy_m: position.coords.accuracy }
          : { location_unavailable_reason: locationReason || "Location not available on this device" },
        etag,
      );
    },
    onSuccess: refresh,
  });
  const fail = useMutation({ mutationFn: () => failVisit(inspection, { reason_code: failCode, reason: failReason }, etag), onSuccess: refresh });
  return (
    <section className={CARD} aria-labelledby="officer-actions">
      <h2 id="officer-actions" className="text-base font-semibold">{t("inspection.visit")}</h2>
      {canCheckIn ? (
        <div className="mt-3 flex flex-col gap-2">
          <label htmlFor={ids.location} className="text-sm font-medium">{t("inspection.locationReason")}</label>
          <input id={ids.location} className={FIELD} value={locationReason} onChange={(e) => setLocationReason(e.target.value)} />
          {arrive.isError ? <ProblemNotice error={arrive.error} /> : null}
          <button type="button" className={BUTTON} disabled={arrive.isPending} onClick={() => arrive.mutate()}>{t("inspection.checkIn")}</button>
        </div>
      ) : null}
      {canFail ? (
        <div className="mt-4 flex flex-col gap-2 border-t border-border pt-4">
          <p className="text-sm text-muted">{t("inspection.failHelp")}</p>
          <label htmlFor={ids.code} className="text-sm font-medium">{t("inspection.failCode")}</label>
          <select id={ids.code} className={FIELD} value={failCode} onChange={(e) => setFailCode(e.target.value)}>
            {FAILED_VISIT_REASONS.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <label htmlFor={ids.reason} className="text-sm font-medium">{t("policy.reason")}</label>
          <textarea id={ids.reason} className={FIELD} rows={2} value={failReason} onChange={(e) => setFailReason(e.target.value)} />
          {fail.isError ? <ProblemNotice error={fail.error} /> : null}
          <button type="button" className={SECONDARY} disabled={fail.isPending || failReason.trim().length < 10} onClick={() => fail.mutate()}>{t("inspection.recordFailedVisit")}</button>
        </div>
      ) : null}
    </section>
  );
}
