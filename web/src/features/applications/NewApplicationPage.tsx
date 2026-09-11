import { useMutation, useQuery } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { createDraft } from "../../api/applications";
import { premisesListQuery } from "../../api/premises";
import { servicesQuery } from "../../api/services";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";

const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 text-sm text-ink";
const BUTTON = "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";

/** UI-06 step 1 (service and premises). The draft is created on the first successful server save
 *  and the wizard continues at /applications/:id/edit. */
export function NewApplicationPage() {
  const navigate = useNavigate();
  const premises = useQuery(premisesListQuery);
  const services = useQuery(servicesQuery);
  const [premisesId, setPremisesId] = useState("");
  const [serviceId, setServiceId] = useState("");
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const premisesField = useId();
  const serviceField = useId();
  const create = useMutation({
    mutationFn: () => createDraft({ premises_id: premisesId, service_id: serviceId }, idempotencyKey),
    onSuccess: async (created) => {
      await navigate(`/applications/${created.application_id}/edit`, { replace: true });
    },
  });
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };
  const available = (services.data ?? []).filter((s) => s.available);

  return (
    <div className="mx-auto max-w-[920px]">
      <h1 className="text-2xl font-semibold text-ink">{t("wizard.title")}</h1>
      <p className="mt-1 text-sm text-muted">{t("wizard.step1.help")}</p>
      <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-4 rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]">
        <div>
          <label htmlFor={serviceField} className="text-sm font-medium">{t("wizard.service")}</label>
          <select id={serviceField} className={FIELD} value={serviceId} onChange={(e) => setServiceId(e.target.value)} required>
            <option value="">{t("applicability.chooseService")}</option>
            {available.map((s) => (
              <option key={s.service_id} value={s.service_id}>{s.title}</option>
            ))}
          </select>
          {services.data && available.length === 0 ? <p className="mt-1 text-sm text-muted">{t("wizard.noService")}</p> : null}
        </div>
        <div>
          <label htmlFor={premisesField} className="text-sm font-medium">{t("wizard.premises")}</label>
          <select id={premisesField} className={FIELD} value={premisesId} onChange={(e) => setPremisesId(e.target.value)} required>
            <option value="">{t("wizard.choosePremises")}</option>
            {(premises.data ?? []).map((p) => (
              <option key={p.premises_id} value={p.premises_id}>{p.display_name} · {p.locality}</option>
            ))}
          </select>
          {premises.data && premises.data.length === 0 ? (
            <p className="mt-1 text-sm text-muted">
              {t("wizard.noPremises")} <Link to="/applicant/premises" className="text-primary">{t("premises.register")}</Link>
            </p>
          ) : null}
        </div>
        {create.isError ? <ProblemNotice error={create.error} /> : null}
        <div className="flex items-center gap-3">
          <button type="submit" disabled={!premisesId || !serviceId || create.isPending} className={BUTTON}>
            {create.isPending ? t("wizard.creating") : t("wizard.start")}
          </button>
          <Link to="/applications" className="text-sm text-muted">{t("wizard.cancel")}</Link>
        </div>
      </form>
    </div>
  );
}
