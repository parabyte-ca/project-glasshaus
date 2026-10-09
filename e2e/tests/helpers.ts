import AxeBuilder from "@axe-core/playwright";
import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const adminEmail = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";

export function adminPassword(): string {
  const password = process.env.E2E_ADMIN_PASSWORD;
  if (!password)
    throw new Error(
      "Set E2E_ADMIN_PASSWORD (GLASSHAUS_ADMIN_PASSWORD from .env)",
    );
  return password;
}

export async function signIn(page: Page, email: string, password: string) {
  await page.goto("/");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(
    page.getByRole("heading", { name: "Projects", level: 1 }),
  ).toBeVisible();
}

/** REST calls as the signed-in browser user (session cookie + CSRF header). */
export async function api(page: Page) {
  const csrf =
    (await page.context().cookies()).find((c) => c.name === "gh_csrf")?.value ??
    "";
  const request: APIRequestContext = page.request;
  return async <T = unknown>(
    method: string,
    path: string,
    data?: unknown,
  ): Promise<T> => {
    const response = await request.fetch(path, {
      method,
      data,
      headers: { "X-CSRF-Token": csrf },
    });
    if (!response.ok())
      throw new Error(
        `${method} ${path} → ${response.status()} ${await response.text()}`,
      );
    return (response.status() === 204 ? null : await response.json()) as T;
  };
}

/** A project key that is unique for this run (keys are 2-10 letters/digits). */
export function uniqueKey(prefix = "E"): string {
  return (prefix + Date.now().toString(36)).toUpperCase().slice(0, 10);
}

export async function makeProject(
  page: Page,
  name = "E2E project",
): Promise<{ id: string; key: string }> {
  const call = await api(page);
  let workspaces = await call<{ id: string }[]>("GET", "/api/v1/workspaces");
  if (workspaces.length === 0) {
    await call("POST", "/api/v1/workspaces", {
      name: "E2E",
      slug: `e2e-${Date.now().toString(36)}`,
    });
    workspaces = await call<{ id: string }[]>("GET", "/api/v1/workspaces");
  }
  return call("POST", "/api/v1/projects", {
    workspace_id: workspaces[0]!.id,
    key: uniqueKey(),
    name,
  });
}

/** WCAG 2.1 A/AA checks with axe-core; fails with a readable list of violations. */
export async function expectAccessible(page: Page, label: string) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const summary = results.violations.map(
    (v) =>
      `${v.id} (${v.impact}): ${v.help}\n  ${v.nodes
        .map((n) => n.target.join(" "))
        .slice(0, 5)
        .join("\n  ")}`,
  );
  expect(summary, `${label}: accessibility violations`).toEqual([]);
}
