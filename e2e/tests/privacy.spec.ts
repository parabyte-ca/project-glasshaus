import { expect, test } from "@playwright/test";

import { api, expectAccessible } from "./helpers";

// About, privacy and source code: reachable from every page, with the licence notices.
test("about page links the source and lists licences", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("link", { name: "About, privacy and source code" })
    .click();
  await expect(
    page.getByRole("heading", { name: "About and privacy", level: 1 }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Source code for this server" }),
  ).toHaveAttribute("href", /^https:\/\//);
  await page.getByText(/^Server \(\d+\)$/).click();
  await expect(page.getByText(/^fastapi /i)).toBeVisible();
  await page.getByText(/^Web app \(\d+\)$/).click();
  await expect(page.getByText(/^react \d/)).toBeVisible();
  await expectAccessible(page, "about");
});

// The audit log is sealed: the integrity check passes on a real stack, including upgraded entries.
test("audit log integrity check passes", async ({ page }) => {
  await page.goto("/admin?tab=audit");
  await page.getByRole("button", { name: "Check integrity" }).click();
  await expect(page.getByText(/^Intact: [\d,]+ entries/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Copy the latest seal" }),
  ).toBeVisible();
  await expectAccessible(page, "audit log");
});

// Erasing a person keeps their work and removes who they were; their own export works first.
test("an admin erases a person after typing their email", async ({ page }) => {
  await page.goto("/");
  const admin = await api(page);
  const stamp = Date.now().toString(36);
  const email = `erase-${stamp}@example.com`;
  await admin("POST", "/api/v1/users", { email, name: `Eve ${stamp}` });
  await page.goto("/admin");
  await page.getByLabel("Search people").fill(stamp);
  const download = page.getByRole("link", {
    name: `Download Eve ${stamp}’s data`,
  });
  await expect(download).toHaveAttribute(
    "href",
    /\/api\/v1\/admin\/users\/.+\/export$/,
  );
  const zip = await page.request.get((await download.getAttribute("href"))!);
  expect(zip.headers()["content-type"]).toBe("application/zip");

  await page.getByRole("button", { name: `Erase Eve ${stamp}` }).click();
  const confirm = page
    .getByRole("button", { name: `Erase Eve ${stamp}` })
    .last();
  await expect(confirm).toBeDisabled();
  await page.getByLabel(`Type ${email} to confirm`).fill(email);
  await confirm.click();
  await expect(
    page.getByText(new RegExp(`Eve ${stamp} was erased`)),
  ).toBeVisible();
  await page.getByLabel("Search people").fill("Former user");
  await expect(
    page.getByRole("cell", { name: "Erased" }).first(),
  ).toBeVisible();
});

test("people can download their own data", async ({ page }) => {
  await page.goto("/account");
  const link = page.getByRole("link", { name: "Download my data" });
  const zip = await page.request.get((await link.getAttribute("href"))!);
  expect(zip.status()).toBe(200);
  expect(zip.headers()["content-type"]).toBe("application/zip");
});
