import { useQuery } from "@tanstack/react-query";

import { readinessQuery, type CheckResult } from "../../api/health";
import { t, type MessageKey } from "../../locales";

const CHECK_LABELS: Partial<Record<string, MessageKey>> = {
  database: "home.apiCheck.database",
  schema: "home.apiCheck.schema",
  configuration: "home.apiCheck.configuration",
};

function checkLabel(name: string): string {
  const key = CHECK_LABELS[name];
  return key ? t(key) : name;
}

function checkResult(result: CheckResult): string {
  return result === "pass" ? t("home.check.pass") : t("home.check.fail");
}

/** The only server-backed element of the B01 shell: real readiness from /api/v1/health/ready. */
export function ApiReadiness() {
  const query = useQuery(readinessQuery);

  let tone = "border-border bg-surface";
  let headline = t("home.apiLoading");
  if (query.isError) {
    tone = "border-danger bg-danger-soft";
    headline = t("home.apiError");
  } else if (query.data?.status === "ready") {
    tone = "border-positive bg-positive-soft";
    headline = t("home.apiReady");
  } else if (query.data?.status === "not_ready") {
    tone = "border-warning bg-warning-soft";
    headline = t("home.apiNotReady");
  }

  return (
    <section
      aria-labelledby="api-status-heading"
      aria-live="polite"
      className={`rounded-[var(--radius-card)] border p-4 shadow-[var(--shadow-card)] ${tone}`}
      data-testid="api-readiness"
      data-state={query.isError ? "error" : query.data?.status ?? "loading"}
    >
      <h2 id="api-status-heading" className="text-base font-semibold text-ink">
        {t("home.apiStatus")}
      </h2>
      <p className="mt-1 text-ink">{headline}</p>
      {query.data ? (
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          {Object.entries(query.data.checks).map(([name, result]) => (
            <div key={name} className="contents">
              <dt className="text-muted">{checkLabel(name)}</dt>
              <dd className={result === "pass" ? "text-positive" : "text-danger"}>
                {result === "pass" ? "✓" : "✗"} {checkResult(result)}
              </dd>
            </div>
          ))}
          <dt className="text-muted">{t("app.modeLabel")}</dt>
          <dd>{query.data.service_mode}</dd>
        </dl>
      ) : null}
      <button
        type="button"
        onClick={() => void query.refetch()}
        disabled={query.isFetching}
        className="mt-4 inline-flex min-h-11 items-center rounded-md border border-border bg-surface px-4 text-sm font-medium text-ink hover:bg-canvas disabled:opacity-60"
      >
        {t("home.refresh")}
      </button>
    </section>
  );
}

export function HomePage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-ink md:text-[28px]">{t("home.title")}</h1>
        <p className="mt-2 max-w-prose text-muted">{t("home.body")}</p>
      </div>
      <ApiReadiness />
    </div>
  );
}
