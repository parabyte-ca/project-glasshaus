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
