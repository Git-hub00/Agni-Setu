import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { CAPABILITIES, approveGrant, deactivateStaff, grantsQuery, proposeGrant, revokeGrant, staffQuery, type CapabilityKey, type Grant, type StaffMember } from "../../api/staff";
import { ProblemNotice } from "../../app/ProblemNotice";
import { useSession } from "../identity/useSession";
import { t } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 py-2 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";
const GHOST = "inline-flex min-h-11 items-center rounded-md border border-border px-3 text-sm font-medium text-ink disabled:opacity-60";
const DANGER = "inline-flex min-h-11 items-center rounded-md border border-danger px-3 text-sm font-medium text-danger disabled:opacity-60";

/** UI-21: roster (roles, powers, workload), grant proposal / approval / revocation with a
 *  reason and version precondition, and deactivation. Read-only for supervisors. */
export function TeamPage() {
  const staff = useQuery(staffQuery);
  const grants = useQuery(grantsQuery);
  if (staff.isPending) return <p className="text-sm text-muted">{t("team.loading")}</p>;
  if (staff.isError) return <ProblemNotice error={staff.error} />;
  const { items, can_manage, scope } = staff.data;
  const proposed = (grants.data?.items ?? []).filter((g) => g.state === "PROPOSED");
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-ink">{t("team.title")}</h1>
        <p className="mt-1 max-w-prose text-sm text-muted">{scope === "GLOBAL" ? t("team.helpAdmin") : t("team.helpSupervisor")}</p>
      </div>
      {can_manage ? <ProposeGrantForm members={items} /> : null}
      {can_manage && proposed.length > 0 ? (
        <section className={CARD} aria-labelledby="team-pending">
          <h2 id="team-pending" className="text-base font-semibold">{t("team.pendingTitle")}</h2>
          <p className="mt-1 text-sm text-muted">{t("team.pendingHelp")}</p>
          <ul className="mt-3 flex flex-col gap-2 text-sm">
            {proposed.map((g) => (
              <GrantRow key={g.grant_id} grant={g} canManage={can_manage} />
            ))}
          </ul>
        </section>
      ) : null}
      <section className={CARD} aria-labelledby="team-roster">
        <h2 id="team-roster" className="text-base font-semibold">{t("team.rosterTitle")}</h2>
        {items.length === 0 ? <p className="mt-2 text-sm text-muted">{t("team.empty")}</p> : null}
        <ul className="mt-3 flex flex-col gap-3">
          {items.map((member) => (
            <MemberRow key={member.principal_id} member={member} canManage={can_manage} />
          ))}
        </ul>
      </section>
    </div>
  );
}

function MemberRow({ member, canManage }: { member: StaffMember; canManage: boolean }) {
  const queryClient = useQueryClient();
  const { principal } = useSession();
  const [reason, setReason] = useState("");
  const [open, setOpen] = useState(false);
  const deactivate = useMutation({
    mutationFn: () => deactivateStaff(member.principal_id, reason.trim(), member.etag),
    onSuccess: async () => {
      setOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["staff"] });
    },
  });
  const isSelf = principal?.id === member.principal_id;
  return (
    <li className="rounded-md border border-border p-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-medium">
            {member.display_name}
            <span className={`ml-2 rounded-md px-2 py-0.5 text-xs ${member.active ? "bg-positive-soft text-positive" : "bg-danger-soft text-danger"}`}>
              {member.active ? t("team.active") : t("team.inactive")}
            </span>
          </p>
          <p className="text-muted">
            {member.roles.filter((r) => r.in_force).map((r) => `${r.role_key}${r.jurisdiction_code ? ` @ ${r.jurisdiction_code}` : ""}`).join(", ") || t("team.noRoles")}
            {" · "}
            {t("team.workload")} {member.workload.active_assignments}
          </p>
        </div>
        {canManage && member.active && !isSelf ? (
          <button type="button" className={DANGER} aria-expanded={open} onClick={() => setOpen((v) => !v)}>{t("team.deactivate")}</button>
        ) : null}
      </div>
      {member.grants.length > 0 ? (
        <ul className="mt-2 flex flex-col gap-1">
          {member.grants.map((g) => (
            <GrantRow key={g.grant_id} grant={g} canManage={canManage} />
          ))}
        </ul>
      ) : null}
      {open ? (
        <form
          className="mt-3 flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            deactivate.mutate();
          }}
        >
          <label className="flex-1 text-sm font-medium">
            {t("team.reason")}
            <input className={FIELD} minLength={5} maxLength={4000} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button type="submit" className={DANGER} disabled={deactivate.isPending || reason.trim().length < 5}>{t("team.confirmDeactivate")}</button>
          {deactivate.isError ? <div className="w-full"><ProblemNotice error={deactivate.error} /></div> : null}
          <p className="w-full text-xs text-muted">{t("team.deactivateHint")}</p>
        </form>
      ) : null}
    </li>
  );
}

function GrantRow({ grant, canManage }: { grant: Grant; canManage: boolean }) {
  const queryClient = useQueryClient();
  const { principal } = useSession();
  const [reason, setReason] = useState("");
  const [mode, setMode] = useState<"approve" | "revoke" | null>(null);
  const act = useMutation({
    mutationFn: () => (mode === "approve" ? approveGrant(grant.grant_id, reason.trim(), grant.etag) : revokeGrant(grant.grant_id, reason.trim(), grant.etag)),
    onSuccess: async () => {
      setMode(null);
      setReason("");
      await queryClient.invalidateQueries({ queryKey: ["staff"] });
    },
  });
  const isPreparer = principal?.id === grant.preparer_id;
  const isSubject = principal?.id === grant.subject_id;
  const canApprove = canManage && grant.state === "PROPOSED" && !isPreparer && !isSubject;
  const canRevoke = canManage && (grant.state === "PROPOSED" || grant.state === "APPROVED");
  return (
    <li className="flex flex-col gap-2 rounded-md bg-canvas p-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>
          <span className="font-medium">{grant.capability}</span> · {grant.scope_kind}
          {grant.subject_display_name ? ` · ${grant.subject_display_name}` : ""}
          <span className="ml-2 rounded-md bg-surface px-2 py-0.5 text-xs">{grant.state}</span>
        </span>
        <span className="flex gap-2">
          {canApprove ? <button type="button" className={GHOST} onClick={() => setMode("approve")}>{t("team.approve")}</button> : null}
          {grant.state === "PROPOSED" && isPreparer ? <span className="text-xs text-muted">{t("team.preparerCannotApprove")}</span> : null}
          {canRevoke ? <button type="button" className={DANGER} onClick={() => setMode("revoke")}>{t("team.revoke")}</button> : null}
        </span>
      </div>
      {mode ? (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            act.mutate();
          }}
        >
          <label className="flex-1 text-sm font-medium">
            {mode === "approve" ? t("team.approvalBasis") : t("team.reason")}
            <input className={FIELD} minLength={mode === "approve" ? 10 : 5} maxLength={4000} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button type="submit" className={BUTTON} disabled={act.isPending || reason.trim().length < (mode === "approve" ? 10 : 5)}>
            {mode === "approve" ? t("team.confirmApprove") : t("team.confirmRevoke")}
          </button>
          <button type="button" className={GHOST} onClick={() => setMode(null)}>{t("team.cancel")}</button>
          {act.isError ? <div className="w-full"><ProblemNotice error={act.error} /></div> : null}
        </form>
      ) : null}
    </li>
  );
}

function ProposeGrantForm({ members }: { members: StaffMember[] }) {
  const queryClient = useQueryClient();
  const [subject, setSubject] = useState("");
  const [capability, setCapability] = useState<CapabilityKey>("case.decide");
  const [scope, setScope] = useState<"GLOBAL" | "JURISDICTION">("JURISDICTION");
  const [jurisdiction, setJurisdiction] = useState("");
  const [reason, setReason] = useState("");
  const ids = { subject: useId(), capability: useId(), scope: useId(), jurisdiction: useId(), reason: useId() };
  const jurisdictions = new Map<string, string>();
  for (const m of members) for (const r of m.roles) if (r.jurisdiction_id && r.jurisdiction_code) jurisdictions.set(r.jurisdiction_id, r.jurisdiction_code);
  const propose = useMutation({
    mutationFn: () =>
      proposeGrant({
        subject_id: subject,
        capability,
        scope_kind: scope,
        ...(scope === "JURISDICTION" ? { jurisdiction_id: jurisdiction } : {}),
        reason: reason.trim(),
      }),
    onSuccess: async () => {
      setReason("");
      await queryClient.invalidateQueries({ queryKey: ["staff"] });
    },
  });
  const ready = subject !== "" && reason.trim().length >= 10 && (scope === "GLOBAL" || jurisdiction !== "");
  return (
    <section className={CARD} aria-labelledby="team-propose">
      <h2 id="team-propose" className="text-base font-semibold">{t("team.proposeTitle")}</h2>
      <p className="mt-1 text-sm text-muted">{t("team.proposeHelp")}</p>
      <form
        className="mt-3 grid gap-3 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          propose.mutate();
        }}
      >
        <div>
          <label htmlFor={ids.subject} className="text-sm font-medium">{t("team.subject")}</label>
          <select id={ids.subject} className={FIELD} value={subject} onChange={(e) => setSubject(e.target.value)}>
            <option value="">{t("team.chooseSubject")}</option>
            {members.filter((m) => m.active).map((m) => (
              <option key={m.principal_id} value={m.principal_id}>{m.display_name}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={ids.capability} className="text-sm font-medium">{t("team.capability")}</label>
          <select id={ids.capability} className={FIELD} value={capability} onChange={(e) => setCapability(e.target.value as CapabilityKey)}>
            {CAPABILITIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor={ids.scope} className="text-sm font-medium">{t("team.scope")}</label>
          <select id={ids.scope} className={FIELD} value={scope} onChange={(e) => setScope(e.target.value as "GLOBAL" | "JURISDICTION")}>
            <option value="JURISDICTION">JURISDICTION</option>
            <option value="GLOBAL">GLOBAL</option>
          </select>
        </div>
        {scope === "JURISDICTION" ? (
          <div>
            <label htmlFor={ids.jurisdiction} className="text-sm font-medium">{t("team.jurisdiction")}</label>
            <select id={ids.jurisdiction} className={FIELD} value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)}>
              <option value="">{t("team.chooseJurisdiction")}</option>
              {[...jurisdictions.entries()].map(([id, code]) => <option key={id} value={id}>{code}</option>)}
            </select>
          </div>
        ) : null}
        <div className="sm:col-span-2">
          <label htmlFor={ids.reason} className="text-sm font-medium">{t("team.reason")}</label>
          <input id={ids.reason} className={FIELD} minLength={10} maxLength={4000} value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        {propose.isError ? <div className="sm:col-span-2"><ProblemNotice error={propose.error} /></div> : null}
        <div className="sm:col-span-2">
          <button type="submit" className={BUTTON} disabled={!ready || propose.isPending}>{t("team.propose")}</button>
        </div>
      </form>
    </section>
  );
}
