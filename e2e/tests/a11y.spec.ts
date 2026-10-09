import { expect, test, type Page } from '@playwright/test';

import { api, expectAccessible, makeProject } from './helpers';

// Automated WCAG 2.1 A/AA checks (axe-core) on every main screen, in light and dark themes.
// Automated checks catch roughly a third of issues; docs/accessibility.md lists the manual checks.

async function setTheme(page: Page, theme: 'light' | 'dark') {
  await page.addInitScript((t) => localStorage.setItem('glasshaus.theme', t), theme);
}

let projectKey = '';
let taskKey = '';

test.beforeAll(async ({ browser }) => {
  const page = await browser.newPage({ storageState: '.auth/admin.json' });
  await page.goto('/');
  const project = await makeProject(page, 'Accessibility');
  const call = await api(page);
  const today = new Date().toISOString().slice(0, 10);
  const t = await call<{ key: string }>('POST', '/api/v1/tasks', {
    project_id: project.id,
    title: 'Check contrast',
    description: 'Run **axe** on every screen.',
    priority: 'high',
    start_date: today,
    due_date: today,
    estimate_minutes: 90,
  });
  await call('POST', '/api/v1/tasks', { project_id: project.id, title: 'Second task', due_date: today });
  projectKey = project.key;
  taskKey = t.key;
  await page.close();
});

const PAGES: [string, () => string][] = [
  ['home', () => '/'],
  ['project list', () => `/projects/${projectKey}`],
  ['project board', () => `/projects/${projectKey}?kind=board`],
  ['project table', () => `/projects/${projectKey}?kind=table`],
  ['project timeline', () => `/projects/${projectKey}?kind=timeline`],
  ['project calendar', () => `/projects/${projectKey}?kind=calendar`],
  ['task drawer', () => `/projects/${projectKey}?task=${taskKey}`],
  ['project report', () => `/projects/${projectKey}/report`],
  ['project settings', () => `/projects/${projectKey}/settings`],
  ['project digests', () => `/projects/${projectKey}/assistant`],
  ['account', () => '/account'],
  ['time', () => '/time'],
  ['workload', () => '/workload'],
  ['dashboards', () => '/dashboards'],
  ['portfolios', () => '/portfolios'],
  ['goals', () => '/goals'],
  ['admin people', () => '/admin?tab=people'],
  ['admin sso', () => '/admin?tab=sso'],
  ['admin provisioning', () => '/admin?tab=provisioning'],
  ['admin integrations', () => '/admin?tab=integrations'],
  ['admin audit', () => '/admin?tab=audit'],
  ['admin ai', () => '/admin?tab=ai'],
  ['admin data', () => '/admin?tab=data'],
];

for (const theme of ['light', 'dark'] as const) {
  test.describe(`${theme} theme`, () => {
    test.beforeEach(async ({ page }) => setTheme(page, theme));

    for (const [name, path] of PAGES) {
      test(name, async ({ page }) => {
        await page.goto(path());
        await page.waitForLoadState('networkidle');
        await expect(page.getByRole('main')).toBeVisible();
        await expect(page.getByRole('status').filter({ hasText: /^Loading/ })).toHaveCount(0);
        await expectAccessible(page, `${name} (${theme})`);
      });
    }

    test('command palette and shortcut help', async ({ page }) => {
      await page.goto('/');
      await expect(page.getByRole('button', { name: /^Search/ })).toBeVisible();
      await page.keyboard.press('ControlOrMeta+k');
      const palette = page.getByRole('dialog', { name: 'Command palette' });
      await palette.getByRole('combobox').fill('Check');
      await expect(palette.getByRole('option').first()).toBeVisible();
      await expectAccessible(page, `palette (${theme})`);
      await page.keyboard.press('Escape');
      await page.keyboard.press('?');
      await expect(page.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeVisible();
      await expectAccessible(page, `shortcut help (${theme})`);
    });
  });
}

test.describe('signed out', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('sign-in page', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByLabel('Email')).toBeVisible();
    await expectAccessible(page, 'sign-in');
  });
});

test('keyboard only: skip link, focus order and dialogs return focus', async ({ page }) => {
  await page.goto(`/projects/${projectKey}`);
  await expect(page.getByLabel('New task title')).toBeVisible();
  await page.keyboard.press('Tab');
  const skip = page.getByRole('link', { name: 'Skip to content' });
  await expect(skip).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/#main$/);

  const trigger = page.getByRole('button', { name: /^Search/ });
  await trigger.focus();
  await page.keyboard.press('Enter');
  const palette = page.getByRole('dialog', { name: 'Command palette' });
  await expect(palette.getByRole('combobox')).toBeFocused();
  // Focus stays inside the dialog.
  for (let i = 0; i < 6; i++) await page.keyboard.press('Tab');
  expect(await palette.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
});
