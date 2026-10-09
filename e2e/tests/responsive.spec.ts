import { expect, test } from '@playwright/test';

import { api, expectAccessible, makeProject } from './helpers';

// Phone-sized viewport: nothing scrolls sideways and the main screens stay accessible.
test('phone layout', async ({ page }) => {
  await page.goto('/');
  const project = await makeProject(page, 'Phone');
  for (const path of ['/', `/projects/${project.key}`, `/projects/${project.key}?kind=board`, '/time', '/account']) {
    await page.goto(path);
    await page.waitForLoadState('networkidle');
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `${path} scrolls sideways`).toBeLessThanOrEqual(1);
    await expectAccessible(page, `${path} (phone)`);
  }
});

// Narrowest common phone: the header fits and the navigation is a menu.
test('phone navigation menu', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 740 });
  await page.goto('/time');
  const nav = page.getByRole('navigation', { name: 'Projects' });
  await expect(nav).toBeHidden();
  const menu = page.getByRole('button', { name: 'Menu' });
  await expect(menu).toHaveAttribute('aria-expanded', 'false');
  await menu.click();
  await expect(nav).toBeVisible();
  await expectAccessible(page, 'open menu (phone)');
  await nav.getByRole('link', { name: 'Home', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Projects', level: 1 })).toBeVisible();
  await expect(nav).toBeHidden();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, 'header scrolls sideways at 375 px').toBeLessThanOrEqual(1);
});

// My tasks on a phone: opens without a connection and syncs a task ticked offline.
test('my tasks offline', async ({ page, context }) => {
  await page.goto('/');
  const project = await makeProject(page, 'Offline');
  const call = await api(page);
  const me = await call<{ id: string }>('GET', '/api/v1/users/me');
  const today = new Date().toISOString().slice(0, 10);
  const title = `Pack the tent ${project.key}`;
  const task = await call<{ id: string; key: string }>('POST', '/api/v1/tasks', {
    project_id: project.id,
    title,
    assignee_id: me.id,
    due_date: today,
  });

  await page.goto('/my');
  await expect(page.getByText(title)).toBeVisible();
  await expectAccessible(page, 'my tasks (phone)');
  // Once the service worker controls the page, a reload caches the app's files for offline use.
  await page.waitForFunction(() => navigator.serviceWorker?.controller !== null);
  await page.reload();
  await expect(page.getByText(title)).toBeVisible();

  await context.setOffline(true);
  await page.reload();
  await expect(page.getByText(/You’re offline/)).toBeVisible();
  await page.getByRole('checkbox', { name: `Mark ${task.key} done` }).click();
  await expect(page.getByText(title)).toBeHidden();
  await expect(page.getByText('(1 waiting)', { exact: false })).toBeVisible();

  await context.setOffline(false);
  await expect(page.getByText(/Synced 1 task/)).toBeVisible({ timeout: 40_000 });
  const done = await call<{ status: { category: string } }>('GET', `/api/v1/tasks/${task.id}`);
  expect(done.status.category).toBe('done');
});
