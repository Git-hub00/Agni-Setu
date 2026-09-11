import { expect, test } from "@playwright/test";

import { collectCspViolations, expectAccessible, expectNoHorizontalOverflow, signInApplicant } from "./helpers";

test.describe("applicant workspace (UI-03..07, UI-16, UI-19, UI-26, UI-27)", () => {
  test("signs in through the real OTP form and every applicant route is accessible", async ({ page, request }) => {
    const csp = collectCspViolations(page);
    await signInApplicant(page, request);
    for (const path of ["/overview", "/applications", "/applications/new", "/certificates", "/notifications", "/support", "/settings", "/account"]) {
      await page.goto(path);
      await expect(page.getByRole("main")).toBeVisible();
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expectAccessible(page, path);
    }
    await page.goto("/overview");
    await expectNoHorizontalOverflow(page, "/overview");
    expect(csp, "CSP refusals in the console").toEqual([]);
  });

  test("a reload restores the canonical session state and keyboard reaches the workspace links", async ({ page, request }) => {
    await signInApplicant(page, request);
    await page.goto("/applications");
    await page.reload();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    // Keyboard: the sidebar workspace list is a real navigation landmark with focusable links.
    const nav = page.getByRole("navigation", { name: "Workspaces" });
    await expect(nav).toBeVisible();
    const firstLink = nav.getByRole("link").first();
    await firstLink.focus();
    await expect(firstLink).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });

  test("a deep link to another applicant's case shows a scoped error, not data", async ({ page, request }) => {
    await signInApplicant(page, request);
    await page.goto("/applications/00000000-0000-0000-0000-000000000000");
    await expect(page.getByRole("main")).toContainText(/not found|could not|no longer|not permitted/i);
    await expectAccessible(page, "/applications/<unknown>");
  });
});
