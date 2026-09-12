import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { conflictsQuery, integrationQuery, integrationsQuery, resolveConflict, testIntegration, type Integration, type IntegrationConflict, type ResolutionOutcome } from "../../api/integrations";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t, type MessageKey } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 py-2 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";
const GHOST = "inline-flex min-h-11 items-center rounded-md border border-border px-3 text-sm font-medium text-ink disabled:opacity-60";

const OUTCOMES: ResolutionOutcome[] = ["APPLY_VERIFIED_SOURCE", "IGNORE_DUPLICATE", "REQUEST_RESEND", "KEEP_QUARANTINED"];

function modeTone(mode: Integration["mode"]): string {
  if (mode === "LIVE") return "bg-danger-soft text-danger";
  if (mode === "SANDBOX") return "bg-warning-soft text-warning";
  return "bg-information-soft text-information";
}

function healthTone(status: Integration["last_health_status"]): string {
  if (status === "OK") return "text-positive";
  if (status === "FAIL") return "text-danger";
  return "text-muted";
}

/** UI-25: provider cards (mode badge, state, capabilities, health, freshness), detail with
 *  field ownership, sanitised inbox rows and entity reflections, allowlisted probes, and the
 *  evidence-based conflict resolution. No secret value is ever shown or entered here. */
export function IntegrationsPage() {
  const list = useQuery(integrationsQuery);
  const conflicts = useQuery(conflictsQuery("OPEN"));
  const [selected, setSelected] = useState<string | null>(null);
  const detail = useQuery(integrationQuery(selected));
  if (list.isPending) return <p className="text-sm text-muted">{t("integrations.loading")}</p>;
  if (list.isError) return <ProblemNotice error={list.error} />;
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-ink">{t("integrations.title")}</h1>
        <p className="mt-1 max-w-prose text-sm text-muted">{t("integrations.help")}</p>
      </div>
      <ul className="grid gap-4 md:grid-cols-2">
        {list.data.items.map((item) => (
          <li key={item.integration_id} className={`${CARD} min-w-0`}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h2 className="text-base font-semibold">{item.display_name}</h2>
                <p className="text-xs text-muted">{item.key} · {item.provider_kind}</p>
              </div>
              <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${modeTone(item.mode)}`}>{item.mode}</span>
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted">{t("integrations.state")}</dt>
                <dd>{item.state}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted">{t("integrations.health")}</dt>
                <dd className={healthTone(item.last_health_status)}>
                  {item.last_health_status}
                  {item.last_health_at ? ` · ${new Date(item.last_health_at).toLocaleString()}` : ""}
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted">{t("integrations.freshness")}</dt>
                <dd>{item.freshness}{item.last_event_at ? ` · ${new Date(item.last_event_at).toLocaleString()}` : ""}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted">{t("integrations.openConflicts")}</dt>
                <dd>{item.open_conflicts}</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-xs uppercase tracking-wide text-muted">{t("integrations.capabilities")}</dt>
                <dd>{item.capabilities.join(", ") || "-"}</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-xs uppercase tracking-wide text-muted">{t("integrations.credential")}</dt>
                <dd>{item.credential_configured ? `${t("integrations.secretRef")} ${item.credential_secret_ref}` : t("integrations.noCredential")}</dd>
              </div>
            </dl>
            <div className="mt-3 flex flex-wrap gap-2">
              <button type="button" className={GHOST} aria-pressed={selected === item.key} onClick={() => setSelected(selected === item.key ? null : item.key)}>
                {t("integrations.inspect")}
              </button>
              <ProbeForm integration={item} />
            </div>
            <p className="mt-3 text-xs text-muted">{item.notice}</p>
          </li>
        ))}
      </ul>
      {selected && detail.data ? (
        <section className={CARD} aria-labelledby="integration-detail">
          <h2 id="integration-detail" className="text-base font-semibold">{detail.data.display_name} · {t("integrations.detail")}</h2>
          <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted">{t("integrations.ownedFields")}</dt>
              <dd>{detail.data.system_of_record_fields.join(", ") || "-"}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted">{t("integrations.allowlist")}</dt>
              <dd>{detail.data.endpoint_allowlist.join(", ") || "-"}</dd>
            </div>
          </dl>
          <h3 className="mt-4 text-sm font-semibold">{t("integrations.entityStates")}</h3>
          {detail.data.entity_states.length === 0 ? <p className="text-sm text-muted">{t("integrations.noEntities")}</p> : null}
          <ul className="mt-1 flex flex-col gap-1 text-sm">
            {detail.data.entity_states.map((s) => (
              <li key={s.source_entity_id} className="rounded-md bg-canvas p-2">
                <span className="font-medium">{s.source_entity_id}</span> · {t("integrations.appliedSequence")} {s.applied_sequence ?? "-"} · {s.applied_source_version ?? "-"}
                <pre className="mt-1 overflow-x-auto text-xs">{JSON.stringify(s.snapshot)}</pre>
              </li>
            ))}
          </ul>
          <h3 className="mt-4 text-sm font-semibold">{t("integrations.recentInbox")}</h3>
          <div className="overflow-x-auto">
            <table className="mt-1 w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-muted">
                  <th className="py-1">{t("integrations.received")}</th>
                  <th className="py-1">{t("integrations.event")}</th>
                  <th className="py-1">{t("integrations.sequence")}</th>
                  <th className="py-1">{t("integrations.state")}</th>
                </tr>
              </thead>
              <tbody>
                {detail.data.recent_inbox.map((row) => (
                  <tr key={row.receipt_id} className="border-t border-border">
                    <td className="py-1 whitespace-nowrap">{new Date(row.received_at).toLocaleString()}</td>
                    <td className="py-1">{row.event_type}<span className="block text-xs text-muted">{row.source_entity_id} · {row.source_event_id}</span></td>
                    <td className="py-1">{row.source_sequence ?? "-"}</td>
                    <td className="py-1">{row.state}{row.disposition ? ` · ${row.disposition}` : ""}{row.error_code ? ` · ${row.error_code}` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {detail.data.recent_inbox.length === 0 ? <p className="mt-1 text-sm text-muted">{t("integrations.noInbox")}</p> : null}
          </div>
        </section>
      ) : null}
      <section className={CARD} aria-labelledby="integration-conflicts">
        <h2 id="integration-conflicts" className="text-base font-semibold">{t("integrations.conflictsTitle")}</h2>
        <p className="mt-1 text-sm text-muted">{t("integrations.conflictsHelp")}</p>
        {conflicts.isError ? <ProblemNotice error={conflicts.error} /> : null}
        {conflicts.data && conflicts.data.items.length === 0 ? <p className="mt-2 text-sm text-muted">{t("integrations.noConflicts")}</p> : null}
        <ul className="mt-3 flex flex-col gap-3">
          {(conflicts.data?.items ?? []).map((c) => (
            <ConflictRow key={c.conflict_id} conflict={c} />
          ))}
        </ul>
      </section>
    </div>
  );
}

function ProbeForm({ integration }: { integration: Integration }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [testKey, setTestKey] = useState(integration.allowed_tests[0] ?? "connectivity");
  const [reason, setReason] = useState("");
  const ids = { key: useId(), reason: useId() };
  const probe = useMutation({
    mutationFn: () => testIntegration(integration.key, { test_case_key: testKey, reason: reason.trim() }, integration.etag),
    onSuccess: async () => {
      setOpen(false);
      setReason("");
      await queryClient.invalidateQueries({ queryKey: ["integrations"] });
    },
  });
  return (
    <div className="flex flex-col gap-2">
      <button type="button" className={GHOST} aria-expanded={open} disabled={integration.state === "DISABLED"} onClick={() => setOpen((v) => !v)}>
        {t("integrations.probe")}
      </button>
      {open ? (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            probe.mutate();
          }}
        >
          <div>
            <label htmlFor={ids.key} className="text-sm font-medium">{t("integrations.probeKey")}</label>
            <select id={ids.key} className={FIELD} value={testKey} onChange={(e) => setTestKey(e.target.value)}>
              {integration.allowed_tests.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
          </div>
          <div className="flex-1">
            <label htmlFor={ids.reason} className="text-sm font-medium">{t("integrations.reason")}</label>
            <input id={ids.reason} className={FIELD} minLength={10} maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          <button type="submit" className={BUTTON} disabled={probe.isPending || reason.trim().length < 10}>{t("integrations.runProbe")}</button>
          {probe.isSuccess ? <p role="status" className="w-full text-xs text-muted">{probe.data.notice}</p> : null}
          {probe.isError ? <div className="w-full"><ProblemNotice error={probe.error} /></div> : null}
        </form>
      ) : null}
    </div>
  );
}

function ConflictRow({ conflict }: { conflict: IntegrationConflict }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [outcome, setOutcome] = useState<ResolutionOutcome>("APPLY_VERIFIED_SOURCE");
  const [reason, setReason] = useState("");
  const [version, setVersion] = useState("");
  const [evidence, setEvidence] = useState("");
  const ids = { outcome: useId(), reason: useId(), version: useId(), evidence: useId() };
  const resolve = useMutation({
    mutationFn: () =>
      resolveConflict(
        conflict.conflict_id,
        {
          outcome,
          reason: reason.trim(),
          ...(outcome === "APPLY_VERIFIED_SOURCE" ? { authoritative_source_version: version.trim() } : {}),
          verification_evidence_refs: evidence.split(",").map((s) => s.trim()).filter(Boolean),
        },
        conflict.etag,
      ),
    onSuccess: async () => {
      setOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["integrations"] });
    },
  });
  const ready = reason.trim().length >= 10 && evidence.trim().length > 0 && (outcome !== "APPLY_VERIFIED_SOURCE" || version.trim().length > 0);
  return (
    <li className="min-w-0 rounded-md border border-border p-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        {/* min-w-0: a flex child defaults to min-width:auto, so the JSON <pre> below would widen
            the page instead of scrolling (360 px overflow found by journeys.spec.ts, B19). */}
        <div className="min-w-0 flex-1 break-words">
          <p className="font-medium">
            {conflict.reason_code} · {conflict.source_entity_id}
            <span className="ml-2 rounded-md bg-canvas px-2 py-0.5 text-xs">{conflict.state}</span>
          </p>
          <p className="text-muted">
            {conflict.integration_key} · {t("integrations.owner")} {conflict.owner_queue ?? "-"} · {new Date(conflict.created_at).toLocaleString()}
          </p>
          <pre className="mt-1 overflow-x-auto rounded-md bg-canvas p-2 text-xs">{JSON.stringify(conflict.detail, null, 1)}</pre>
        </div>
        {conflict.state === "OPEN" ? (
          <button type="button" className={GHOST} aria-expanded={open} onClick={() => setOpen((v) => !v)}>{t("integrations.resolve")}</button>
        ) : null}
      </div>
      {open ? (
        <form
          className="mt-3 grid gap-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            resolve.mutate();
          }}
        >
          <div>
            <label htmlFor={ids.outcome} className="text-sm font-medium">{t("integrations.outcome")}</label>
            <select id={ids.outcome} className={FIELD} value={outcome} onChange={(e) => setOutcome(e.target.value as ResolutionOutcome)}>
              {OUTCOMES.map((o) => <option key={o} value={o}>{t(`integrations.outcome.${o}` as MessageKey)}</option>)}
            </select>
          </div>
          {outcome === "APPLY_VERIFIED_SOURCE" ? (
            <div>
              <label htmlFor={ids.version} className="text-sm font-medium">{t("integrations.sourceVersion")}</label>
              <input id={ids.version} className={FIELD} value={version} onChange={(e) => setVersion(e.target.value)} />
            </div>
          ) : null}
          <div className="sm:col-span-2">
            <label htmlFor={ids.evidence} className="text-sm font-medium">{t("integrations.evidence")}</label>
            <input id={ids.evidence} className={FIELD} value={evidence} onChange={(e) => setEvidence(e.target.value)} />
          </div>
          <div className="sm:col-span-2">
            <label htmlFor={ids.reason} className="text-sm font-medium">{t("integrations.reason")}</label>
            <input id={ids.reason} className={FIELD} minLength={10} maxLength={4000} value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          {resolve.isError ? <div className="sm:col-span-2"><ProblemNotice error={resolve.error} /></div> : null}
          <div className="sm:col-span-2 flex flex-wrap items-center gap-3">
            <button type="submit" className={BUTTON} disabled={!ready || resolve.isPending}>{t("integrations.confirmResolve")}</button>
            <p className="text-xs text-muted">{t("integrations.resolveHint")}</p>
          </div>
        </form>
      ) : null}
    </li>
  );
}
