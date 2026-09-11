import AxeBuilder from "@axe-core/playwright";
import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const VIEWPORTS = [360, 390, 768, 1280, 1440] as const;

/** WCAG 2.2 AA scan; fails on serious/critical violations and reports the rest for review. */
export async function expectAccessible(page: Page, label: string): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"])
    .analyze();
  const blocking = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  const summary = results.violations.map((v) => `${v.impact ?? "n/a"} ${v.id}: ${v.nodes.length} node(s) - ${v.help}`);
  if (summary.length > 0) console.log(`[axe] ${label}: ${summary.join(" | ")}`);
  expect(blocking, `${label}: serious/critical accessibility violations`).toEqual([]);
}

/** No page-level horizontal overflow at each required width (UI spec s.2 / test plan s.8). */
export async function expectNoHorizontalOverflow(page: Page, label: string): Promise<void> {
  for (const width of VIEWPORTS) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(150);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    const culprits = overflow > 0
      ? await page.evaluate(() =>
          Array.from(document.querySelectorAll("body *"))
            .filter((el) => el.getBoundingClientRect().right > document.documentElement.clientWidth + 1)
            .slice(0, 5)
            .map((el) => `${el.tagName.toLowerCase()}.${el.className.toString().split(" ").slice(0, 3).join(".")} right=${Math.round(el.getBoundingClientRect().right)}`),
        )
      : [];
    expect(overflow, `${label} @ ${width}px overflows by ${overflow}px: ${culprits.join(" | ")}`).toBeLessThanOrEqual(0);
  }
  await page.setViewportSize({ width: 1280, height: 900 });
}

/** Collect console errors that indicate a Content-Security-Policy refusal. */
export function collectCspViolations(page: Page): string[] {
  const violations: string[] = [];
  page.on("console", (message) => {
    const text = message.text();
    if (/Content Security Policy|Refused to (load|execute|apply|connect)/i.test(text)) violations.push(text);
  });
  return violations;
}

/** Applicant sign-in through the real form; the code is read from the demo inbox API. A fresh
 *  synthetic contact per sign-in keeps the OTP resend cooldown and hourly limits out of the way. */
export async function signInApplicant(page: Page, request: APIRequestContext): Promise<string> {
  const contact = `e2e.applicant.${Date.now()}.${Math.floor(Math.random() * 1e6)}@example.test`;
  await page.goto("/sign-in");
  await page.getByLabel(/Email address/i).fill(contact);
  await page.getByRole("button", { name: "Send code" }).click();
  await expect(page.getByLabel("Six-digit code")).toBeVisible();
  const inbox = await request.get(`/api/v1/demo/inbox?channel=EMAIL&contact=${encodeURIComponent(contact)}`);
  expect(inbox.ok()).toBeTruthy();
  const body = (await inbox.json()) as { data: { messages: { body: string }[] } };
  const latest = body.data.messages[0]?.body ?? ""; // the inbox lists newest first
  const match = /\b(\d{6})\b/.exec(latest);
  if (!match) throw new Error("demo inbox did not deliver a code");
  await page.getByLabel("Six-digit code").fill(match[1] ?? "");
  await page.getByRole("button", { name: "Verify and sign in" }).click();
  const signedIn = page.getByRole("navigation", { name: "Workspaces" }).getByRole("link").first();
  const alert = page.getByRole("alert");
  await expect(signedIn.or(alert)).toBeVisible();
  if (await alert.isVisible()) throw new Error(`sign-in refused: ${await alert.innerText()}`);
  return contact;
}

/** Staff sign-in through the real Keycloak form (local realm; demo passwords). */
export async function signInStaff(page: Page, username: string): Promise<void> {
  await page.goto("/sign-in");
  await page.getByRole("link", { name: "Continue with staff identity" }).click();
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(`demo-${username}-password`);
  await page.locator("#kc-login").click();
  await page.waitForURL(/127\.0\.0\.1:5173|localhost:5173/);
  await expect(page.getByRole("navigation", { name: "Workspaces" })).toBeVisible();
}
