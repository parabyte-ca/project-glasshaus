import { expect, test } from '@playwright/test';

import { api, expectAccessible, makeProject, signIn } from './helpers';

const ENTERPRISE = 'urn:ietf:params:scim:schemas:extension:enterprise:2.0:User';

// The identity provider sends a manager over SCIM; the manager then sees My team, with their report's
// work in a project they are not a member of, and can open the report's task list.
test('a manager sees their team from SCIM', async ({ page, browser, baseURL, playwright }) => {
  await page.goto('/');
  const admin = await api(page);
  const project = await makeProject(page, 'Team work');
  const stamp = Date.now().toString(36);
  const managerEmail = `mgr-${stamp}@example.com`;
  const password = `Pw-${stamp}-manager`;
  const manager = await admin<{ id: string }>('POST', '/api/v1/users', {
    email: managerEmail,
    name: 'Mona Manager',
    password,
  });

  const { token } = await admin<{ token: string }>('POST', '/api/v1/admin/scim-tokens', { name: 'e2e' });
  const scim = await playwright.request.newContext({
    baseURL,
    extraHTTPHeaders: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/scim+json' },
  });
  const created = await scim.post('/scim/v2/Users', {
    data: {
      userName: `rep-${stamp}@example.com`,
      displayName: 'Rita Report',
      title: 'Designer',
      [ENTERPRISE]: { department: 'Studio', manager: { value: manager.id } },
    },
  });
  expect(created.status()).toBe(201);
  const rita = (await created.json()) as { id: string };
  await scim.dispose();

  await admin('PUT', `/api/v1/projects/${project.id}/members`, { user_id: rita.id, role: 'editor' });
  await admin('POST', '/api/v1/tasks', {
    project_id: project.id,
    title: 'Draft the brand guide',
    assignee_id: rita.id,
  });

  const context = await browser.newContext({ baseURL, storageState: { cookies: [], origins: [] } });
  const mona = await context.newPage();
  await signIn(mona, managerEmail, password);
  await mona.getByRole('link', { name: 'My team' }).click();
  await expect(mona.getByRole('heading', { name: 'My team', level: 1 })).toBeVisible();
  const card = mona.getByRole('listitem').filter({ has: mona.getByRole('heading', { name: 'Rita Report' }) });
  await expect(card).toContainText('Designer · Studio');
  await expect(card.getByRole('link', { name: 'Team work' })).toHaveCount(0); // not a member: no link
  await expectAccessible(mona, 'my team');

  await card.getByRole('button', { name: "See Rita Report's tasks" }).click();
  const dialog = mona.getByRole('dialog', { name: /Rita Report: open work/ });
  await expect(dialog.getByText('Draft the brand guide')).toBeVisible();
  await expectAccessible(mona, 'report tasks dialog');
  await mona.keyboard.press('Escape');
  await context.close();

  // Admins choose what managers see.
  await page.goto('/admin?tab=provisioning');
  await expect(page.getByRole('heading', { name: 'Managers from Microsoft Entra ID' })).toBeVisible();
  await expect(page.getByRole('radio', { name: 'Their reports’ work in every project' })).toBeChecked();
  await expectAccessible(page, 'provisioning');
});
