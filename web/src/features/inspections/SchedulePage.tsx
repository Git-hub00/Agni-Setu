import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { scheduleQuery } from "../../api/inspections";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-4 shadow-[var(--shadow-card)]";

function startOfWeek(date: Date): Date {
  const d = new Date(date);
  const day = (d.getDay() + 6) % 7; // Monday = 0
  d.setDate(d.getDate() - day);
  d.setHours(0, 0, 0, 0);
  return d;
}

/** UI-11: accessible week agenda (a list per day, never drag-and-drop only) with officer filter,
 *  bookings and unavailability from the bounded /schedule window. Scheduling itself happens in
 *  the inspection detail dialog after server conflict checks. */
export function SchedulePage() {
  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date()));
  const weekEnd = new Date(weekStart.getTime() + 7 * 24 * 3600 * 1000);
  const [officer, setOfficer] = useState("");
  const query = useQuery(scheduleQuery(weekStart.toISOString(), weekEnd.toISOString()));
  const days = Array.from({ length: 7 }, (_, i) => new Date(weekStart.getTime() + i * 24 * 3600 * 1000));
  const bookings = (query.data?.bookings ?? []).filter((b) => !officer || b.officer_id === officer);
  const unavailability = (query.data?.unavailability ?? []).filter((u) => !officer || u.officer_id === officer);
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-ink">{t("schedule.title")}</h1>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <button type="button" className="min-h-11 rounded-md border border-border px-3" onClick={() => setWeekStart(new Date(weekStart.getTime() - 7 * 24 * 3600 * 1000))}>{t("schedule.prevWeek")}</button>
          <span aria-live="polite">{weekStart.toLocaleDateString()} – {new Date(weekEnd.getTime() - 1).toLocaleDateString()} · {query.data?.timezone ?? "Asia/Kolkata"}</span>
          <button type="button" className="min-h-11 rounded-md border border-border px-3" onClick={() => setWeekStart(new Date(weekStart.getTime() + 7 * 24 * 3600 * 1000))}>{t("schedule.nextWeek")}</button>
          <label className="flex items-center gap-2">
            <span>{t("schedule.officer")}</span>
            <select className="min-h-11 rounded-md border border-border bg-canvas px-2" value={officer} onChange={(e) => setOfficer(e.target.value)}>
              <option value="">{t("schedule.allOfficers")}</option>
              {(query.data?.officers ?? []).map((o) => (
                <option key={o.officer_id} value={o.officer_id}>{o.display_name}</option>
              ))}
            </select>
          </label>
        </div>
      </div>
      {query.isPending ? <p className="text-sm text-muted">{t("schedule.loading")}</p> : null}
      {query.isError ? <ProblemNotice error={query.error} /> : null}
      <ol className="grid gap-3 lg:grid-cols-7" aria-label={t("schedule.agenda")}>
        {days.map((day) => {
          const next = new Date(day.getTime() + 24 * 3600 * 1000);
          const dayBookings = bookings.filter((b) => b.booking_start && new Date(b.booking_start) < next && (b.booking_end ? new Date(b.booking_end) > day : true));
          const dayUnavailable = unavailability.filter((u) => new Date(u.starts_at) < next && new Date(u.ends_at) > day);
          return (
            <li key={day.toISOString()} className={CARD}>
              <h2 className="text-sm font-semibold">{day.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}</h2>
              <ul className="mt-2 flex flex-col gap-2 text-sm">
                {dayBookings.length === 0 && dayUnavailable.length === 0 ? <li className="text-muted">{t("schedule.free")}</li> : null}
                {dayBookings.map((b) => (
                  <li key={b.assignment_id} className="rounded-md bg-primary-soft p-2">
                    <Link to={`/inspections/${b.inspection_id}`} className="font-medium text-primary">{b.public_reference ?? b.inspection_id.slice(0, 8)}</Link>
                    <div>{b.booking_start ? new Date(b.booking_start).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : ""}–{b.booking_end ? new Date(b.booking_end).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : ""}</div>
                    <div className="text-xs text-muted">{b.officer_name} · {b.inspection_status}</div>
                  </li>
                ))}
                {dayUnavailable.map((u) => (
                  <li key={u.availability_id} className="rounded-md bg-warning-soft p-2 text-warning">
                    {t("schedule.unavailable")} · {u.reason_code}
                  </li>
                ))}
              </ul>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
