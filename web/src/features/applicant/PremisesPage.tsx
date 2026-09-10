import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";

import { premisesListQuery, registerPremises, type PremisesInput } from "../../api/premises";
import { checkApplicability, servicesQuery, type Applicability } from "../../api/services";
import { ProblemNotice } from "../../app/ProblemNotice";
import { t } from "../../locales";

const EMPTY: PremisesInput = {
  display_name: "",
  address_line1: "",
  address_line2: "",
  locality: "",
  ward_key: "",
  postal_code: "",
  category_key: "",
  area_sqm: "",
  height_m: "",
  floor_count: 1,
  occupancy_count: null,
};

const CARD = "rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]";
const FIELD = "mt-1 block w-full min-h-11 rounded-md border border-border bg-canvas px-3 text-sm text-ink";
const BUTTON =
  "inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-medium text-white hover:bg-primary-hover disabled:opacity-60";

/** UI-04: owned premises, registration and the nonbinding applicability preview (FR-03). The
 *  server scopes every list and validates every write; the preview never decides anything. */
export function PremisesPage() {
  const premises = useQuery(premisesListQuery);
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold text-ink">{t("premises.title")}</h1>
      <section aria-labelledby="premises-list" className={CARD}>
        <h2 id="premises-list" className="text-base font-semibold text-ink">
          {t("premises.list")}
        </h2>
        {premises.isPending ? <p className="mt-2 text-sm text-muted">{t("premises.loading")}</p> : null}
        {premises.isError ? <ProblemNotice error={premises.error} /> : null}
        {premises.data && premises.data.length === 0 ? (
          <p className="mt-2 text-sm text-muted">{t("premises.empty")}</p>
        ) : null}
        {premises.data && premises.data.length > 0 ? (
          <table className="mt-3 w-full text-left text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-wide text-muted">
                <th scope="col" className="py-2">{t("premises.field.displayName")}</th>
                <th scope="col" className="py-2">{t("premises.field.locality")}</th>
                <th scope="col" className="py-2">{t("premises.field.ward")}</th>
                <th scope="col" className="py-2">{t("premises.field.category")}</th>
              </tr>
            </thead>
            <tbody>
              {premises.data.map((p) => (
                <tr key={p.premises_id} className="border-t border-border">
                  <td className="py-2 font-medium">{p.display_name}</td>
                  <td className="py-2">{p.locality}</td>
                  <td className="py-2">{p.ward_key}</td>
                  <td className="py-2">{p.category_key}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </section>
      <div className="grid gap-6 lg:grid-cols-2">
        <RegisterPremisesForm />
        <ApplicabilityPanel />
      </div>
    </div>
  );
}

function RegisterPremisesForm() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<PremisesInput>(EMPTY);
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());
  const ids = {
    name: useId(),
    address: useId(),
    locality: useId(),
    ward: useId(),
    postal: useId(),
    category: useId(),
    area: useId(),
    height: useId(),
    floors: useId(),
    occupancy: useId(),
  };
  const register = useMutation({
    mutationFn: () =>
      registerPremises(
        {
          ...form,
          address_line2: form.address_line2 || undefined,
          occupancy_count: form.occupancy_count ?? undefined,
        },
        idempotencyKey,
      ),
    onSuccess: async () => {
      setForm(EMPTY);
      setIdempotencyKey(crypto.randomUUID());
      await queryClient.invalidateQueries({ queryKey: ["premises"] });
    },
  });
  const set = (key: keyof PremisesInput, value: string) =>
    setForm((prev) => ({
      ...prev,
      [key]:
        key === "floor_count" ? Number(value) : key === "occupancy_count" ? (value === "" ? null : Number(value)) : value,
    }));
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    register.mutate();
  };

  return (
    <section aria-labelledby="premises-register" className={CARD}>
      <h2 id="premises-register" className="text-base font-semibold text-ink">
        {t("premises.register")}
      </h2>
      <p className="mt-1 text-sm text-muted">{t("premises.registerHelp")}</p>
      <form onSubmit={onSubmit} className="mt-4 grid gap-3 sm:grid-cols-2" noValidate>
        <div className="sm:col-span-2">
          <label htmlFor={ids.name} className="text-sm font-medium">{t("premises.field.displayName")}</label>
          <input id={ids.name} className={FIELD} value={form.display_name} onChange={(e) => set("display_name", e.target.value)} required />
        </div>
        <div className="sm:col-span-2">
          <label htmlFor={ids.address} className="text-sm font-medium">{t("premises.field.address")}</label>
          <input id={ids.address} className={FIELD} value={form.address_line1} onChange={(e) => set("address_line1", e.target.value)} required />
        </div>
        <div>
          <label htmlFor={ids.locality} className="text-sm font-medium">{t("premises.field.locality")}</label>
          <input id={ids.locality} className={FIELD} value={form.locality} onChange={(e) => set("locality", e.target.value)} required />
        </div>
        <div>
          <label htmlFor={ids.ward} className="text-sm font-medium">{t("premises.field.ward")}</label>
          <input id={ids.ward} className={FIELD} value={form.ward_key} onChange={(e) => set("ward_key", e.target.value)} placeholder="W-01" required />
        </div>
        <div>
          <label htmlFor={ids.postal} className="text-sm font-medium">{t("premises.field.postalCode")}</label>
          <input id={ids.postal} className={FIELD} inputMode="numeric" value={form.postal_code} onChange={(e) => set("postal_code", e.target.value)} required />
        </div>
        <div>
          <label htmlFor={ids.category} className="text-sm font-medium">{t("premises.field.category")}</label>
          <input id={ids.category} className={FIELD} value={form.category_key} onChange={(e) => set("category_key", e.target.value)} placeholder="Restaurant" required />
        </div>
        <div>
          <label htmlFor={ids.area} className="text-sm font-medium">{t("premises.field.area")}</label>
          <input id={ids.area} className={FIELD} inputMode="decimal" value={form.area_sqm} onChange={(e) => set("area_sqm", e.target.value)} required />
        </div>
        <div>
          <label htmlFor={ids.height} className="text-sm font-medium">{t("premises.field.height")}</label>
          <input id={ids.height} className={FIELD} inputMode="decimal" value={form.height_m} onChange={(e) => set("height_m", e.target.value)} required />
        </div>
        <div>
          <label htmlFor={ids.floors} className="text-sm font-medium">{t("premises.field.floors")}</label>
          <input id={ids.floors} className={FIELD} type="number" min={1} value={form.floor_count} onChange={(e) => set("floor_count", e.target.value)} required />
        </div>
        <div>
          <label htmlFor={ids.occupancy} className="text-sm font-medium">{t("premises.field.occupancy")}</label>
          <input id={ids.occupancy} className={FIELD} type="number" min={0} value={form.occupancy_count ?? ""} onChange={(e) => set("occupancy_count", e.target.value)} />
        </div>
        <div className="sm:col-span-2 flex flex-col gap-3">
          {register.isError ? <ProblemNotice error={register.error} /> : null}
          {register.isSuccess ? (
            <p role="status" className="rounded-md bg-positive-soft p-3 text-sm text-positive">{t("premises.registered")}</p>
          ) : null}
          <button type="submit" disabled={register.isPending} className={BUTTON}>
            {register.isPending ? t("premises.saving") : t("premises.save")}
          </button>
        </div>
      </form>
    </section>
  );
}

function ApplicabilityPanel() {
  const services = useQuery(servicesQuery);
  const [serviceId, setServiceId] = useState("");
  const [category, setCategory] = useState("");
  const serviceIdField = useId();
  const categoryField = useId();
  const check = useMutation({ mutationFn: () => checkApplicability(serviceId, category) });
  const selected = services.data?.find((s) => s.service_id === serviceId);
  const onCheck = (event: FormEvent) => {
    event.preventDefault();
    check.mutate();
  };

  return (
    <section aria-labelledby="applicability" className={CARD}>
      <h2 id="applicability" className="text-base font-semibold text-ink">{t("applicability.title")}</h2>
      <p className="mt-1 text-sm text-muted">{t("applicability.help")}</p>
      <form onSubmit={onCheck} className="mt-4 flex flex-col gap-3">
        <div>
          <label htmlFor={serviceIdField} className="text-sm font-medium">{t("applicability.service")}</label>
          <select
            id={serviceIdField}
            className={FIELD}
            value={serviceId}
            onChange={(e) => {
              setServiceId(e.target.value);
              setCategory("");
              check.reset();
            }}
            required
          >
            <option value="">{t("applicability.chooseService")}</option>
            {(services.data ?? []).map((s) => (
              <option key={s.service_id} value={s.service_id} disabled={!s.available}>
                {s.title} {s.available ? "" : `- ${s.explanation}`}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={categoryField} className="text-sm font-medium">{t("applicability.category")}</label>
          <select id={categoryField} className={FIELD} value={category} onChange={(e) => setCategory(e.target.value)} required disabled={!selected}>
            <option value="">{t("applicability.chooseCategory")}</option>
            {(selected?.allowed_categories ?? []).map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
        {check.isError ? <ProblemNotice error={check.error} /> : null}
        <button type="submit" disabled={!serviceId || !category || check.isPending} className={BUTTON}>
          {check.isPending ? t("applicability.checking") : t("applicability.check")}
        </button>
      </form>
      {check.data ? <ApplicabilityResult result={check.data} /> : null}
    </section>
  );
}

function ApplicabilityResult({ result }: { result: Applicability }) {
  return (
    <div data-testid="applicability-result" className="mt-4 rounded-md border border-border bg-canvas p-4 text-sm">
      <p className="font-medium">{result.applicable ? t("applicability.applicable") : t("applicability.notApplicable")}</p>
      <p className="mt-1 text-muted">{result.explanation}</p>
      {result.required_documents.length > 0 ? (
        <>
          <h3 className="mt-3 text-xs font-semibold uppercase tracking-wide text-muted">{t("applicability.documents")}</h3>
          <ul className="mt-1 list-disc pl-5">
            {result.required_documents.map((doc) => (
              <li key={doc}>{doc}</li>
            ))}
          </ul>
        </>
      ) : null}
      {result.policy_number !== null ? (
        <p className="mt-3 text-xs text-muted">
          {t("applicability.policy")} v{result.policy_number} · {result.inspection_required ? t("applicability.inspectionRequired") : t("applicability.inspectionNotRequired")}
        </p>
      ) : null}
      <p className="mt-3 inline-block rounded-md bg-warning-soft px-2 py-1 text-xs text-warning">{t("applicability.nonbinding")}</p>
    </div>
  );
}
