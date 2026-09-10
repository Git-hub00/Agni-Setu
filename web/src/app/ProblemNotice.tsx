import { ApiError, NetworkError } from "../api/errors";
import { t } from "../locales";

/** Renders an RFC 9457 problem from the API: code, detail, field violations and request id.
 *  Bodies are shown, never logged (engineering standards s.3). */
export function ProblemNotice({ error }: { error: unknown }) {
  if (!error) {
    return null;
  }
  if (error instanceof NetworkError) {
    return (
      <p role="alert" className="rounded-md border border-danger bg-danger-soft p-3 text-sm text-danger">
        {t("home.apiError")}
      </p>
    );
  }
  if (error instanceof ApiError) {
    const violations = error.body?.violations ?? [];
    return (
      <div role="alert" className="rounded-md border border-danger bg-danger-soft p-3 text-sm text-danger">
        <p className="font-medium">
          {error.code ? `${error.code}: ` : ""}
          {error.message}
        </p>
        {violations.length > 0 ? (
          <ul className="mt-2 list-disc pl-5">
            {violations.map((v) => (
              <li key={`${v.pointer}:${v.code}`}>
                <code>{v.pointer}</code> {v.message}
              </li>
            ))}
          </ul>
        ) : null}
        {error.body?.request_id ? (
          <p className="mt-2 text-xs">
            {t("signIn.reference")} {error.body.request_id}
          </p>
        ) : null}
      </div>
    );
  }
  return (
    <p role="alert" className="rounded-md border border-danger bg-danger-soft p-3 text-sm text-danger">
      {t("error.title")}
    </p>
  );
}
