import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";

import { certificatesQuery, type CertificateSummary, type PendingIssuance } from "../../api/certificates";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-4 shadow-[var(--shadow-card)]";
const TAB = "inline-flex min-h-11 items-center rounded-md px-3 text-sm font-medium";

type Tab = "PUBLISHED" | "PENDING" | "HISTORICAL";

/** UI-16: the register distinguishes published instruments, pending issuance and historical or
 *  invalid records. A reserved number is never shown as an issued active instrument. */
export function CertificatesPage() {
  const [params, setParams] = useSearchParams();
  const [term, setTerm] = useState(params.get("q") ?? "");
  const tab = (params.get("tab") as Tab | null) ?? "PUBLISHED";
  const query = useQuery(certificatesQuery({ q: params.get("q") ?? undefined }));
  const setTab = (next: Tab) => {
    const search = new URLSearchParams(params);
    search.set("tab", next);
    setParams(search);
  };
  const submitSearch = () => {
    const search = new URLSearchParams(params);
    if (term.trim()) search.set("q", term.trim());
    else search.delete("q");
    setParams(search);
  };
  if (query.isPending) return <p className="text-sm text-muted">{t("review.loading")}</p>;
  if (query.isError) return <ProblemNotice error={query.error} />;
  const { items, pending_issuance: pending, demo_notice } = query.data;
  const published = items.filter((c) => c.effective_status === "ACTIVE");
  const historical = items.filter((c) => c.effective_status !== "ACTIVE");
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold text-ink">{t("certificates.title")}</h1>
        <p className="text-sm text-muted">{t("certificates.help")}</p>
        {demo_notice ? <p className="mt-1 inline-block rounded-md bg-warning-soft px-2 py-0.5 text-xs font-medium text-warning">{demo_notice}</p> : null}
      </div>
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); submitSearch(); }}>
        <label className="flex flex-col text-sm">
          <span className="font-medium">{t("certificates.search")}</span>
          <input className="mt-1 min-h-11 w-72 rounded-md border border-border bg-canvas px-3 text-sm" value={term} onChange={(e) => setTerm(e.target.value)} />
        </label>
        <button type="submit" className="inline-flex min-h-11 items-center rounded-md border border-border bg-surface px-4 text-sm font-medium">{t("applications.search")}</button>
      </form>
      <div role="tablist" aria-label={t("certificates.title")} className="flex flex-wrap gap-2">
        {(["PUBLISHED", "PENDING", "HISTORICAL"] as Tab[]).map((key) => (
          <button key={key} role="tab" type="button" aria-selected={tab === key} className={`${TAB} ${tab === key ? "bg-primary text-white" : "border border-border bg-surface text-ink"}`} onClick={() => setTab(key)}>
            {key === "PUBLISHED" ? t("certificates.tab.published") : key === "PENDING" ? t("certificates.tab.pending") : t("certificates.tab.historical")} ({key === "PUBLISHED" ? published.length : key === "PENDING" ? pending.length : historical.length})
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === "PENDING" ? <PendingList rows={pending} /> : <CertificateList rows={tab === "PUBLISHED" ? published : historical} />}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const tone = status === "ACTIVE" ? "bg-positive-soft text-positive" : status === "REVOKED" ? "bg-danger-soft text-danger" : "bg-warning-soft text-warning";
  return <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${tone}`}>{status}</span>;
}

function CertificateList({ rows }: { rows: CertificateSummary[] }) {
  if (rows.length === 0) return <p className="text-sm text-muted">{t("certificates.empty")}</p>;
  return (
    <ul className="flex flex-col gap-2">
      {rows.map((c) => (
        <li key={c.certificate_id} className={`${CARD} flex flex-wrap items-center justify-between gap-3 text-sm`}>
          <div>
            <p className="font-medium">
              {c.certificate_number} {c.is_demo ? <span className="ml-2 rounded-md bg-warning-soft px-2 py-0.5 text-xs text-warning">{t("certificates.demo")}</span> : null}
            </p>
            <p className="text-muted">{c.premises.display_name} · {c.premises.locality} · {c.outcome_kind}</p>
            <p className="text-muted">{t("certificates.issued")} {new Date(c.issued_at).toLocaleDateString()} · {t("certificates.validUntil")} {c.valid_until ? new Date(c.valid_until).toLocaleDateString() : "-"}</p>
          </div>
          <div className="flex items-center gap-3">
            <StatusBadge status={c.effective_status} />
            <Link to={`/certificates/${c.certificate_id}`} className="inline-flex min-h-11 items-center rounded-md border border-border px-3 font-medium text-ink">{t("certificates.open")}</Link>
          </div>
        </li>
      ))}
    </ul>
  );
}

function PendingList({ rows }: { rows: PendingIssuance[] }) {
  if (rows.length === 0) return <p className="text-sm text-muted">{t("certificates.empty")}</p>;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm text-muted">{t("certificates.pendingHint")}</p>
      <ul className="flex flex-col gap-2">
        {rows.map((r) => (
          <li key={r.issuance_request_id} className={`${CARD} text-sm`}>
            <p className="font-medium">{r.certificate_number} · {r.public_reference ?? r.application_id.slice(0, 8)} · {r.premises.display_name}</p>
            <p className="text-muted">{r.state} · {t("certificates.dependency")}: {r.dependency} · {r.attempts} {t("certificates.attempts")}{r.last_error_code ? ` · ${r.last_error_code}` : ""}</p>
            <p className="text-xs text-muted">{new Date(r.updated_at).toLocaleString()}</p>
            <Link to={`/applications/${r.application_id}`} className="text-primary">{t("review.viewCase")}</Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
