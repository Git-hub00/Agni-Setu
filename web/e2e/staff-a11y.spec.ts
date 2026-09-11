import { expect, test } from "@playwright/test";

import { collectCspViolations, expectAccessible, expectNoHorizontalOverflow, signInStaff } from "./helpers";

test.describe("staff workspaces (UI-09..15, UI-20..25)", () => {
  test("supervisor routes are accessible after the real Keycloak sign-in", async ({ page }) => {
    const csp = collectCspViolations(page);
    await signInStaff(page, "anita");
    for (const path of ["/overview", "/inspections", "/schedule", "/reviews", "/monitoring", "/reports", "/audit", "/team", "/certificates"]) {
      await page.goto(path);
      await expect(page.getByRole("main")).toBeVisible();
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expectAccessible(page, `anita ${path}`);
    }
    await page.goto("/reports");
    await expectNoHorizontalOverflow(page, "/reports");
    expect(csp, "CSP refusals in the console").toEqual([]);
  });

  test("administrator planes are accessible and never show a secret value", async ({ page }) => {
    await signInStaff(page, "arjun");
    for (const path of ["/operations", "/integrations", "/team", "/policy", "/audit"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expectAccessible(page, `arjun ${path}`);
    }
    await page.goto("/integrations");
    await expect(page.getByText("SIMULATED").first()).toBeVisible();
    await expect(page.getByRole("main")).not.toContainText("demo-partner-shared-secret-not-for-live");
  });

  test("an officer is kept out of the management planes by the server", async ({ page }) => {
    await signInStaff(page, "priya");
    await page.goto("/operations");
    await expect(page.getByRole("main")).toContainText(/not permitted|forbidden|no access|Action is not permitted/i);
    await page.goto("/inspections");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expectAccessible(page, "priya /inspections");
  });
});
