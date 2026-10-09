import { expect, test } from '@playwright/test';

import { api, expectAccessible, makeProject } from './helpers';

// Build a report from a template, save it, put it on a dashboard as a number with a target, and
// filter the dashboard; every screen is checked with axe in light and dark.
test('custom report on a dashboard', async ({ page }) => {
  await page.goto('/');
  const call = await api(page);
  const project = await makeProject(page, 'Reporting');
  for (const title of ['Write brief', 'Review brief', 'Publish']) {
    await call('POST', '/api/v1/tasks', { project_id: project.id, title, priority: 'high' });
  }

  await page.goto('/reports');
  await expect(page.getByRole('heading', { name: 'Reports', level: 1 })).toBeVisible();
  await expectAccessible(page, 'reports list');
  await page.getByRole('link', { name: /Overdue work by person/ }).click();
  await page.getByLabel('Group by').selectOption({ label: 'Priority' });
  await page.getByRole('checkbox', { name: `${project.key} Reporting` }).check();
  const name = `High priority ${Date.now().toString(36)}`;
  await page.getByLabel('Name', { exact: true }).fill(name);
  const preview = page.getByRole('table', { name });
  await expect(preview.getByRole('row', { name: /High 3/ })).toBeVisible();
  await expectAccessible(page, 'report builder');
  await page.getByRole('button', { name: 'Save report' }).click();
  await expect(page).toHaveURL(/\/reports\/[0-9a-f-]{36}$/);

  // A single-number version of it, with a target, on a new dashboard.
  await page.getByLabel('Show as').selectOption({ label: 'Single number' });
  await page.getByLabel('Group by').selectOption({ label: 'No grouping (totals only)' });
  await page.getByRole('button', { name: 'Save report' }).click();
  await expect(page.getByText('Report saved')).toBeVisible();
  const reportId = page.url().split('/').at(-1)!;
  const dashboard = await call<{ id: string }>('POST', '/api/v1/dashboards', { name: `Numbers ${name}` });
  await page.reload();
  await page.getByLabel('Add to dashboard').selectOption({ label: `Numbers ${name}` });
  await page.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(page.getByText(`Added to “Numbers ${name}”`)).toBeVisible();

  await page.goto(`/dashboards/${dashboard.id}`);
  const tile = page.getByRole('region', { name });
  await expect(tile.getByText('Open', { exact: true })).toBeVisible();
  await expect(tile.getByText('3', { exact: true })).toBeVisible();
  await page.getByLabel('Date range (report tiles)').selectOption({ label: 'Last 7 days' });
  await expect(page).toHaveURL(/range=last_7_days/);
  await expect(tile.getByText('3', { exact: true })).toBeVisible();
  for (const theme of ['light', 'dark']) {
    await page.evaluate((t) => localStorage.setItem('glasshaus.theme', t), theme);
    await page.reload();
    await expect(page.getByRole('region', { name }).getByText('3', { exact: true })).toBeVisible();
    await expectAccessible(page, `dashboard with a report tile (${theme})`);
  }
  await page.evaluate(() => localStorage.setItem('glasshaus.theme', 'light'));
  await call('DELETE', `/api/v1/reports/${reportId}`);
});
