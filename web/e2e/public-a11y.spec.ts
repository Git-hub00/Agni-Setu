import { expect, test } from "@playwright/test";

import { collectCspViolations, expectAccessible, expectNoHorizontalOverflow } from "./helpers";

test.describe("public routes (UI-01, UI-02, UI-18)", () => {
  test("home, sign-in and verify are accessible, reflow and load under the CSP", async ({ page }) => {
    const csp = collectCspViolations(page);
    for (const path of ["/", "/sign-in", "/verify"]) {
      await page.goto(path);
      await expect(page.getByRole("main")).toBeVisible();
      await expectAccessible(page, path);
      await expectNoHorizontalOverflow(page, path);
    }
    expect(csp, "CSP refusals in the console").toEqual([]);
  });

  test("the security headers reach the browser", async ({ request }) => {
    const shell = await request.get("/");
    const headers = shell.headers();
    expect(headers["content-security-policy"]).toContain("default-src 'self'");
    expect(headers["content-security-policy"]).toContain("frame-ancestors 'none'");
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["x-frame-options"]).toBe("DENY");
    expect(headers["referrer-policy"]).toBe("same-origin");
    const api = await request.get("/api/v1/health/ready");
    expect(api.headers()["content-security-policy"]).toContain("default-src 'none'");
    expect(api.headers()["x-content-type-options"]).toBe("nosniff");
  });

  test("keyboard-only navigation reaches sign-in and the verify form", async ({ page }) => {
    await page.goto("/");
    // Skip link is the first focusable control.
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
    // Tab until the "Sign in" header link receives focus, then activate it with Enter.
    let reached = false;
    for (let i = 0; i < 25 && !reached; i += 1) {
      await page.keyboard.press("Tab");
      reached = await page.getByRole("link", { name: "Sign in" }).evaluate((el) => el === document.activeElement);
    }
    expect(reached, "Sign in link reachable by keyboard").toBeTruthy();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/sign-in$/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    // The verify form works without a pointer: type a number and submit with Enter.
    await page.goto("/verify");
    const field = page.getByRole("textbox").first();
    await field.focus();
    await page.keyboard.type("AGNI-DEMO-2026-101");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("main")).toContainText(/ACTIVE|SUSPENDED|REVOKED|EXPIRED|SUPERSEDED|not find|could not|unknown/i);
  });

  test("reduced motion and 200% zoom keep the shell usable", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await expect(page.getByRole("main")).toBeVisible();
    await page.setViewportSize({ width: 640, height: 900 }); // ~200% zoom of a 1280 layout
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
