import { expect, test } from "@playwright/test";

import { expectAccessible } from "./helpers";

test("Admin › Updates shows this version and how to set up upgrades", async ({
  page,
}) => {
  await page.goto("/admin?tab=updates");
  await expect(page.getByRole("heading", { name: "Updates" })).toBeVisible();
  const version = await page.evaluate(
    async () => (await (await fetch("/api/v1/version")).json()).version,
  );
  await expect(
    page.getByText("This server").locator("xpath=following-sibling::dd[1]"),
  ).toHaveText(version);
  await expect(page.getByRole("button", { name: "Check now" })).toBeVisible();
  await expectAccessible(page, "updates");
});
