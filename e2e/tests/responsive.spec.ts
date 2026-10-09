import { expect, test } from '@playwright/test';

import { expectAccessible, makeProject } from './helpers';

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
  await nav.getByRole('link', { name: 'Home' }).click();
  await expect(page.getByRole('heading', { name: 'Projects', level: 1 })).toBeVisible();
  await expect(nav).toBeHidden();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, 'header scrolls sideways at 375 px').toBeLessThanOrEqual(1);
});
