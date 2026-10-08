import { expect, test } from '@playwright/test';

import { api, makeProject, uniqueKey } from './helpers';

test('create a project, add a task, edit it, comment and complete it', async ({ page }) => {
  const key = uniqueKey('W');
  await page.goto('/');
  const form = page.getByRole('region', { name: 'New project' });
  if (await form.getByLabel('First, name a workspace').isVisible()) {
    await form.getByLabel('First, name a workspace').fill('E2E');
    await form.getByRole('button', { name: 'Create workspace' }).click();
  }
  await form.getByLabel('Key').fill(key);
  await form.getByLabel('Name', { exact: true }).fill('Launch site');
  await form.getByRole('button', { name: 'Create project' }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${key}`));
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Launch site');

  await page.getByLabel('New task title').fill('Write the launch post');
  await page.keyboard.press('Enter');
  await page.getByRole('button', { name: /Write the launch post/ }).first().click();

  const drawer = page.getByRole('dialog');
  await expect(drawer.getByLabel('Title')).toHaveValue('Write the launch post');
  await drawer.getByLabel('Title').fill('Write and publish the launch post');
  await drawer.getByLabel('Title').blur();
  await drawer.getByLabel('Add a comment').fill('Draft is in the shared folder');
  await drawer.getByRole('button', { name: 'Comment' }).click();
  await expect(drawer.getByText('Draft is in the shared folder')).toBeVisible();
  await drawer.getByLabel('Status').selectOption({ label: 'Done' });
  await expect(drawer.getByLabel('Status')).toHaveValue(/.+/);
  await drawer.getByRole('button', { name: 'Close task' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);

  const call = await api(page);
  const tasks = await call<{ items: { title: string; status: { category: string } }[] }>(
    'GET',
    `/api/v1/tasks?project_id=${(await call<{ id: string }>('GET', `/api/v1/projects/by-key/${key}`)).id}`,
  );
  expect(tasks.items.map((t) => [t.title, t.status.category])).toEqual([
    ['Write and publish the launch post', 'done'],
  ]);
});

test('every layout renders the same tasks', async ({ page }) => {
  const project = await makeProject(page, 'Layouts');
  const call = await api(page);
  for (const title of ['Plan', 'Build', 'Test']) {
    await call('POST', '/api/v1/tasks', {
      project_id: project.id,
      title,
      start_date: new Date().toISOString().slice(0, 10),
      due_date: new Date(Date.now() + 3 * 86_400_000).toISOString().slice(0, 10),
    });
  }
  for (const kind of ['list', 'board', 'table', 'timeline', 'calendar']) {
    await page.goto(`/projects/${project.key}?kind=${kind}`);
    await expect(page.getByRole('button', { name: kind[0]!.toUpperCase() + kind.slice(1), pressed: true })).toBeVisible();
    await expect(page.getByText('Build').first()).toBeVisible();
  }
});

test('command palette and keyboard shortcuts', async ({ page }) => {
  const project = await makeProject(page, 'Palette');
  const call = await api(page);
  const created = await call<{ key: string }>('POST', '/api/v1/tasks', {
    project_id: project.id,
    title: 'Renew the TLS certificate',
  });
  await page.goto('/');
  await expect(page.getByRole('button', { name: /^Search/ })).toBeVisible();
  await page.keyboard.press('ControlOrMeta+k');
  const palette = page.getByRole('dialog', { name: 'Command palette' });
  await palette.getByRole('combobox').fill('TLS certificate');
  await palette.getByRole('option', { name: new RegExp(`${created.key} Renew`) }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${project.key}\\?task=${created.key}`));
  await expect(page.getByRole('dialog').getByLabel('Title')).toHaveValue('Renew the TLS certificate');
  await page.keyboard.press('Escape');
  // Single-key shortcuts are ignored while a dialog is open, so wait for the drawer to close.
  await expect(page.getByRole('dialog')).toHaveCount(0);

  await page.keyboard.press('c');
  await expect(page.getByLabel('New task title')).toBeFocused();
  await page.getByLabel('New task title').blur();
  await page.keyboard.press('?');
  await expect(page.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.keyboard.press('g');
  await page.keyboard.press('t');
  await expect(page).toHaveURL(/\/time$/);
});

test('installable: manifest and offline shell', async ({ page }) => {
  await page.goto('/');
  const manifest = await (await page.request.get('/manifest.webmanifest')).json();
  expect(manifest).toMatchObject({ name: 'Project Glasshaus', display: 'standalone', start_url: '/' });
  const scope = await page.evaluate(async () => (await navigator.serviceWorker.ready).scope);
  expect(scope).toMatch(/\/$/);
  // The worker never caches API responses.
  await page.reload();
  const cached = await page.evaluate(async () => {
    const keys = await caches.keys();
    const urls: string[] = [];
    for (const k of keys) for (const r of await (await caches.open(k)).keys()) urls.push(new URL(r.url).pathname);
    return urls;
  });
  expect(cached.length).toBeGreaterThan(0);
  expect(cached.filter((u) => u.startsWith('/api'))).toEqual([]);
});
