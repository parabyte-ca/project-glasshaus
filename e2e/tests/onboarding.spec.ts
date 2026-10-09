import { expect, test } from "@playwright/test";

import { api, expectAccessible, makeProject, signIn } from "./helpers";

// A brand-new person: the tour starts by itself once, the checklist tracks real work, tips appear
// after skipping, and everything is remembered on the account.
test("first-run onboarding for a new person", async ({
  page,
  browser,
  baseURL,
}) => {
  await page.goto("/");
  const admin = await api(page);
  const project = await makeProject(page, "Onboarding");
  const email = `new-${Date.now().toString(36)}@example.com`;
  const password = `Pw-${Date.now()}-onboarding`;
  const person = await admin<{ id: string }>("POST", "/api/v1/users", {
    email,
    name: "New Person",
    password,
  });
  await admin("PUT", `/api/v1/projects/${project.id}/members`, {
    user_id: person.id,
    role: "editor",
  });

  const context = await browser.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
  });
  const newcomer = await context.newPage();
  await signIn(newcomer, email, password);

  // Checklist: docked, nothing done yet.
  const checklist = newcomer.getByRole("region", { name: "Getting started" });
  await expect(checklist.getByRole("progressbar")).toHaveAttribute(
    "aria-valuenow",
    "0",
  );

  // Tour starts on the first project visit; keyboard moves it; Escape skips it.
  await newcomer.goto(`/projects/${project.key}`);
  const card = newcomer.getByRole("dialog", { name: "Create a task" });
  await expect(card).toBeVisible();
  await expectAccessible(newcomer, "product tour");
  await newcomer.keyboard.press("ArrowRight");
  await expect(
    newcomer.getByRole("dialog", { name: "Your tasks" }),
  ).toBeVisible();
  await newcomer.keyboard.press("Escape");
  await expect(
    newcomer.getByRole("dialog", { name: "Your tasks" }),
  ).toBeHidden();

  // After skipping: no tour on reload, tips instead.
  await newcomer.reload();
  await expect(
    newcomer.getByRole("button", { name: "Tip: Timeline view" }),
  ).toBeVisible();
  await expect(
    newcomer.getByRole("dialog", { name: "Create a task" }),
  ).toBeHidden();
  await newcomer.getByRole("button", { name: "Tip: Timeline view" }).click();
  await newcomer
    .getByRole("dialog", { name: "Timeline view" })
    .getByRole("button", { name: "Got it" })
    .click();
  await expect(
    newcomer.getByRole("button", { name: "Tip: Timeline view" }),
  ).toBeHidden();

  // Real work ticks the checklist (created a task with a due date).
  await (
    await api(newcomer)
  )("POST", "/api/v1/tasks", {
    project_id: project.id,
    title: "Plan",
    due_date: "2026-12-01",
  });
  await newcomer.reload();
  await expect(checklist.getByRole("progressbar")).toHaveAttribute(
    "aria-valuenow",
    "50",
  );

  // Restart from Help and finish it.
  await newcomer.getByRole("button", { name: "Product tour" }).click();
  await expect(
    newcomer.getByRole("dialog", { name: "Create a task" }),
  ).toBeVisible();
  for (let i = 0; i < 3; i++)
    await newcomer.getByRole("button", { name: /Next/ }).click();
  await newcomer
    .getByRole("dialog", { name: "People" })
    .getByRole("button", { name: /Done/ })
    .click();
  await expect(checklist.getByRole("progressbar")).toHaveAttribute(
    "aria-valuenow",
    "75",
  );
  const state = await (
    await api(newcomer)
  )<{ tour: string; dismissed_tips: string[] }>(
    "GET",
    "/api/v1/users/me/onboarding",
  );
  expect(state.tour).toBe("completed");
  expect(state.dismissed_tips).toEqual(["timeline"]);

  // Minimize and dismiss are remembered.
  await checklist.getByRole("button", { name: "Minimize" }).click();
  await newcomer.reload();
  await newcomer
    .getByRole("button", { name: /Getting started · 3\/4/ })
    .click();
  await checklist.getByRole("button", { name: "Dismiss" }).click();
  await newcomer.reload();
  await expect(checklist).toBeHidden();
  await context.close();
});
