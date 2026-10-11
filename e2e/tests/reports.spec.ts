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
  await expect(page.getByRole('heading', { name: 'Email me this report' })).toBeVisible();
  // An alert on the report's Open total: 3 open tasks is above 2, so checking now turns it on.
  const alertPanel = page.locator('section', { has: page.getByRole('heading', { name: 'Alert me' }) });
  await alertPanel.getByLabel('When').selectOption({ label: 'Open' });
  await alertPanel.getByLabel('Number').fill('2');
  await alertPanel.getByRole('button', { name: 'Create alert' }).click();
  await alertPanel.getByRole('button', { name: 'Check now' }).click();
  await expect(alertPanel.getByText('Open is above 2')).toBeVisible();
  await expectAccessible(page, 'saved report with email settings');

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

  // A Teams channel with a scheduled post of this kind of report (the panel is checked with axe).
  const teams = await call<{ id: string }>('POST', '/api/v1/integrations', {
    kind: 'teams',
    name: `Teams ${name}`,
    url: 'https://example.webhook.office.com/hook',
  });
  await page.goto('/admin?tab=integrations');
  await page
    .getByRole('row', { name: new RegExp(`Teams ${name}`) })
    .getByRole('button', { name: 'Scheduled posts' })
    .click();
  const posts = page.locator('section', { has: page.getByRole('heading', { name: `Scheduled posts to Teams ${name}` }) });
  await posts.getByLabel('Post', { exact: true }).selectOption({ label: 'A project’s status' });
  await posts.getByLabel('Project').selectOption({ label: `${project.key} Reporting` });
  await posts.getByRole('button', { name: 'Add post' }).click();
  await expect(posts.getByText(`Status: ${project.key} Reporting`)).toBeVisible();
  await expectAccessible(page, 'scheduled channel posts');
  await call('DELETE', `/api/v1/integrations/${teams.id}`);

  await page.goto('/admin?tab=backups');
  await expect(page.getByRole('heading', { name: 'Backups', level: 2 })).toBeVisible();
  await expectAccessible(page, 'admin backups');
});
