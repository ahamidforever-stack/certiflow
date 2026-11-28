// Walkthrough: sign in → new job → confirm glossary → review editor (edit, re-run, reject, preview)
// → approve with confirmation → release files → audit log. Mock LLM: free and offline.
import { expect, test, type Page } from "@playwright/test";
import { join } from "node:path";

const pdf = join(process.env.E2E_DIR!, "certificate.pdf");

async function signIn(page: Page) {
  await page.goto("/");
  await page.fill("#u", "translator1");
  await page.fill("#p", "e2e-pass-123");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("link", { name: "New job", exact: true })).toBeVisible();
}

test("review flow from upload to release", async ({ page }) => {
  await signIn(page);

  // new job
  await page.getByRole("link", { name: "New job", exact: true }).click();
  await page.setInputFiles('input[type="file"]', pdf);
  await page.selectOption("#src", "en");
  await page.selectOption("#tgt", "ar");
  await page.getByRole("radio").filter({ hasText: "Certified" }).first().click();
  await page.getByRole("button", { name: "Start translation" }).click();
  await expect(page).toHaveURL(/\/jobs\/J/);
  const jobUrl = page.url();

  // glossary gate
  await page.getByRole("button", { name: "Confirm glossary" }).click();

  // review editor
  await page.getByRole("link", { name: /Open the review editor/ }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved" })).toBeVisible();
  const cardId = await page.locator("article").filter({ has: page.locator('textarea[aria-label^="Translation of block"]') })
    .nth(1).getAttribute("id");
  const card = page.locator(`article[id="${cardId}"]`);   // fixed by id: textareas turn read-only during a re-run
  const box = card.locator('textarea[aria-label^="Translation of block"]');
  await box.fill("نص راجعه المترجم");
  await expect(page.getByRole("status").filter({ hasText: "Unsaved changes" })).toBeVisible();
  await card.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved" })).toBeVisible();

  // re-run the translator on that block, then reject its change: the reviewer's text comes back
  await card.getByRole("checkbox").check();
  await page.getByRole("button", { name: /Run an agent again/ }).click();   // selection bar opens the re-run dialog
  await page.getByRole("dialog").getByText("Translation", { exact: true }).click();
  await page.fill("#rr-ins", "formal register");
  await page.getByRole("button", { name: /Run on 1 block/ }).click();
  await expect(card.getByText(/Change by Translation/)).toBeVisible();
  await expect(box).not.toHaveValue("نص راجعه المترجم");
  await card.getByRole("button", { name: /Reject/ }).last().click();
  await expect(box).toHaveValue("نص راجعه المترجم");

  // watermarked preview with the stamp
  const href = await page.getByRole("link", { name: "Preview PDF" }).getAttribute("href");
  const prev = await page.request.get(href!);
  expect(prev.status()).toBe(200);
  expect(prev.headers()["content-type"]).toContain("application/pdf");

  // approve with confirmation
  await page.goto(jobUrl);
  await page.getByRole("button", { name: /Approve and stamp/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Certified stamp");
  await dialog.getByRole("button", { name: /Approve and release/ }).click();
  const pdfLink = page.locator('a[download][href$=".pdf"]').first();
  await expect(pdfLink).toBeVisible({ timeout: 180_000 });
  const file = await page.request.get((await pdfLink.getAttribute("href"))!);
  expect((await file.body()).subarray(0, 4).toString()).toBe("%PDF");

  // audit log
  await page.getByRole("link", { name: "Audit log" }).click();
  await expect(page.getByRole("cell", { name: "Edited a block" })).toBeVisible();
  await expect(page.getByRole("cell", { name: /Rejected an agent change/ })).toBeVisible();
  await expect(page.getByRole("cell", { name: /Re-run finished/ })).toBeVisible();
  if (process.env.E2E_SHOTS) await page.screenshot({ path: join(process.env.E2E_SHOTS, "audit.en.png"), fullPage: true });
  await page.getByRole("button", { name: "People" }).click();
  await expect(page.getByRole("cell", { name: /Model call/ })).toHaveCount(0);
});

test("editor and audit log in Arabic are right-to-left", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "Account" }).click();            // user menu → interface language
  await page.getByRole("menuitem", { name: /Interface language/ }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await page.getByRole("navigation").getByRole("link", { name: "كل المهام" }).click();
  await page.locator('a[href^="/jobs/J"]').first().click();
  await page.getByRole("link", { name: "سجل التدقيق" }).click();
  await expect(page.getByRole("heading", { name: "سجل التدقيق" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "عدّل فقرة" })).toBeVisible();
  if (process.env.E2E_SHOTS) await page.screenshot({ path: join(process.env.E2E_SHOTS, "audit.ar.png"), fullPage: true });
  await page.getByRole("button", { name: "الحساب" }).click();   // leave the user's language as it was
  await page.getByRole("menuitem", { name: /لغة الواجهة/ }).click();
});
