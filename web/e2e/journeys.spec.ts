/**
 * B19 role-journey route walk (task card B19 "every enabled route functional"; docs/11 s.3 case
 * 6 of every FR: direct navigation, reload, narrow viewport, keyboard reachability, accessible
 * headings). Runs against the live local stack with the deterministic demo personas and real
 * sign-ins; each role visits every route it is entitled to, opens the first record of every list
 * it owns, reloads it and checks the page at 360 px. Loading / failed / stale states are covered
 * by the vitest page tests next to each page; business outcomes are covered by the API-level
 * acceptance run (scripts/dev/acceptance_run.py).
 *
 * Screen cases claimed here (partial: navigation, reload, narrow viewport, axe):
 * AT-01-06 AT-02-06 AT-03-06 AT-04-06 AT-05-06 AT-06-06 AT-07-06 AT-08-06 AT-09-06 AT-10-06
 * AT-11-06 AT-12-06 AT-13-06 AT-14-06 AT-15-06 AT-16-06 AT-17-06 AT-18-06 AT-19-06 AT-20-06
 * AT-21-06 AT-22-06 AT-23-06 AT-24-06 AT-25-06 AT-26-06 AT-27-06 AT-28-06 AT-29-06 AT-30-06
 */
import { expect, test, type Page } from "@playwright/test";

import { expectAccessible, signInApplicant, signInStaff } from "./helpers";

/** Generous waits: each walk reloads and re-bootstraps the session on a small Docker VM. */
const SLOW_HOST_MS = 30_000;
test.describe.configure({ timeout: 300_000 });

async function csrfToken(page: Page): Promise<string> {
  const cookies = await page.context().cookies();
  return cookies.find((c) => c.name === "csrftoken")?.value ?? "";
}

/** Same-origin API call with the browser session (cookies) and the CSRF double-submit header. */
async function apiPost<T>(page: Page, path: string, body: unknown, extra: Record<string, string> = {}): Promise<{ status: number; data: T; etag: string }> {
  const response = await page.request.post(`/api/v1${path}`, {
    data: body,
    headers: { "Content-Type": "application/json", "X-CSRFToken": await csrfToken(page), "Idempotency-Key": crypto.randomUUID(), ...extra },
  });
  const json = (await response.json()) as { data: T };
  return { status: response.status(), data: json.data, etag: response.headers()["etag"] ?? "" };
}

/** Direct navigation -> heading -> reload -> heading -> 360 px without horizontal overflow -> axe. */
async function walk(page: Page, path: string, label = path): Promise<void> {
  await page.goto(path);
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: SLOW_HOST_MS });
  await page.reload();
  // A reload re-bootstraps the session (/me) before the page renders; on the 3 GB demo VM that
  // can take well over 10 s while the api serves the previous page's queries.
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: SLOW_HOST_MS });
  await page.setViewportSize({ width: 360, height: 780 });
  await page.waitForTimeout(150);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, `${label} overflows at 360 px by ${overflow}px`).toBeLessThanOrEqual(0);
  await page.setViewportSize({ width: 1280, height: 900 });
  await expectAccessible(page, label);
}

/** Open the first record linked from a list route; records whether a row existed. */
async function walkFirstDetail(page: Page, listPath: string, hrefPrefix: string): Promise<string | null> {
  await page.goto(listPath);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const link = page.locator(`main a[href^="${hrefPrefix}"]`).first();
  if ((await link.count()) === 0) {
    test.info().annotations.push({ type: "note", description: `${listPath}: no ${hrefPrefix} record to open` });
    return null;
  }
  const href = await link.getAttribute("href");
  await link.click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: SLOW_HOST_MS });
  await walk(page, href ?? listPath, `${listPath} -> first record`);
  return href;
}

test.describe("public entry (UI-01, UI-02, UI-18)", () => {
  test("public routes, an unknown verification token and an unknown URL are distinct, accessible pages", async ({ page }) => {
    await walk(page, "/");
    await walk(page, "/sign-in");
    await walk(page, "/verify");
    await page.goto("/verify/not-a-real-token");
    // Unknown -> "Record not found"; the public route is rate-limited per client, so a busy demo
    // host may answer "Too many" instead. Either way nothing is ever rendered as ACTIVE.
    await expect(page.getByRole("main")).toContainText(/Record not found|Unable to verify|Too many/i, { timeout: SLOW_HOST_MS });
    await expect(page.getByRole("main")).not.toContainText(/\bACTIVE\b/);
    await expectAccessible(page, "/verify/<unknown>");
    await page.goto("/definitely-not-a-route");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expectAccessible(page, "/<unknown route>");
  });
});

test.describe("applicant journey (UI-03..07, UI-16, UI-19, UI-26, UI-27)", () => {
  test("a new applicant registers premises, opens a draft in the wizard and every applicant route survives reload at 360 px", async ({ page, request }) => {
    await signInApplicant(page, request);
    // Canonical records through the same API the wizard uses (docs/24 premises + draft contracts).
    const premises = await apiPost<{ premises_id: string }>(page, "/premises", {
      display_name: "E2E Journey Cafe",
      address_line1: "12 Journey Lane (synthetic)",
      locality: "Karol Bagh",
      ward_key: "W-01",
      postal_code: "110005",
      category_key: "Restaurant",
      area_sqm: "120.00",
      height_m: "4.50",
      floor_count: 1,
    });
    expect(premises.status, "premises registered").toBe(201);
    const services = await page.request.get("/api/v1/services");
    const catalogue = (await services.json()) as { data: { items: { key: string; service_id: string; available: boolean }[] } };
    const service = catalogue.data.items.find((s) => s.key === "demo-fire-noc" && s.available);
    expect(service, "demo-fire-noc available").toBeTruthy();
    const draft = await apiPost<{ application_id: string; draft_reference: string }>(page, "/applications", {
      premises_id: premises.data.premises_id,
      service_id: service?.service_id,
    });
    expect(draft.status, "draft created").toBe(201);

    await walk(page, `/applications/${draft.data.application_id}`, "draft detail (UI-07)");
    await expect(page.getByRole("main")).toContainText(draft.data.draft_reference);
    await walk(page, `/applications/${draft.data.application_id}/edit`, "wizard (UI-06)");
    await page.goto("/applications");
    await expect(page.getByRole("main")).toContainText(draft.data.draft_reference);
    for (const path of ["/overview", "/applications", "/applications/new", "/applicant/premises", "/certificates", "/notifications", "/support", "/settings", "/account"]) {
      await walk(page, path);
    }
    // Keyboard: Tab from the top of the document reaches an interactive control inside a landmark.
    await page.goto("/applications");
    await page.keyboard.press("Tab");
    const focused = await page.evaluate(() => document.activeElement?.tagName ?? "");
    expect(["A", "BUTTON", "INPUT"]).toContain(focused);
  });
});

test.describe("supervisor journey (UI-05, UI-07, UI-09..11, UI-14..17, UI-19, UI-21..23)", () => {
  test("anita opens the first record of every queue she owns and every route survives reload at 360 px", async ({ page }) => {
    await signInStaff(page, "anita");
    for (const path of ["/overview", "/applications", "/inspections", "/schedule", "/reviews", "/monitoring", "/reports", "/audit", "/team", "/certificates", "/notifications", "/support", "/settings", "/account"]) {
      await walk(page, path);
    }
    const caseHref = await walkFirstDetail(page, "/applications", "/applications/");
    if (caseHref) {
      await walk(page, `${caseHref}/review`, "review page (UI-14)");
    }
    await walkFirstDetail(page, "/inspections", "/inspections/");
    await walkFirstDetail(page, "/certificates", "/certificates/");
    await walkFirstDetail(page, "/support", "/support/");
  });
});

test.describe("officer and administrator journeys (UI-10..13, UI-20, UI-24, UI-25)", () => {
  test("priya reaches her field routes and the first assigned inspection; management planes stay closed", async ({ page }) => {
    await signInStaff(page, "priya");
    for (const path of ["/inspections", "/schedule", "/sync", "/notifications", "/account"]) {
      await walk(page, path);
    }
    await walkFirstDetail(page, "/inspections", "/inspections/");
    await page.goto("/operations");
    await expect(page.getByRole("main")).toContainText(/not permitted|forbidden|no access|Action is not permitted/i);
  });

  test("arjun reaches every administration plane and the first policy record", async ({ page }) => {
    await signInStaff(page, "arjun");
    for (const path of ["/operations", "/integrations", "/team", "/policy", "/audit", "/settings"]) {
      await walk(page, path);
    }
    await walkFirstDetail(page, "/policy", "/policy/");
  });
});
