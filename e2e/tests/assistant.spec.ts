import { expect, test } from '@playwright/test';

import { api, expectAccessible, makeProject } from './helpers';

// The project assistant: a project admin turns it on, writes a digest, and everyone sees it.
test('project assistant digest', async ({ page }) => {
  await page.goto('/');
  const project = await makeProject(page, 'Assistant');
  const call = await api(page);
  const late = new Date(Date.now() - 3 * 86_400_000).toISOString().slice(0, 10);
  await call('POST', '/api/v1/tasks', { project_id: project.id, title: 'Renew the domain', due_date: late });

  await page.goto(`/projects/${project.key}`);
  await page.getByRole('link', { name: 'Digests' }).click();
  await expect(page.getByRole('heading', { name: 'Digests', level: 1 })).toBeVisible();
  await page.getByRole('button', { name: 'Turn on' }).click();
  await expect(page.getByText(/Next digest/).first()).toBeVisible();
  await page.getByRole('button', { name: 'Write a digest now' }).click();

  const digest = page.getByRole('article');
  await expect(digest.getByRole('heading', { name: new RegExp(`${project.key} stand-up`) })).toBeVisible();
  const overdue = digest.getByRole('region', { name: 'Overdue' });
  await expect(overdue).toContainText('Renew the domain');
  await expect(overdue).toContainText('3 days late');
  await expectAccessible(page, 'project digests');

  // The rules suggest an owner for the unassigned, overdue task; approving applies it.
  const queue = page.getByRole('region', { name: /Suggestions/ });
  const owner = queue.getByRole('listitem').filter({ hasText: 'New owner' });
  await expect(owner).toContainText('Renew the domain');
  await owner.getByRole('button', { name: 'Approve' }).click();
  await expect(page.getByText(/assigned$/).first()).toBeVisible();
  await expect(queue.getByRole('listitem').filter({ hasText: 'New owner' })).toHaveCount(0);

  // Notes become proposed tasks; approving creates one.
  await queue.getByLabel('Turn meeting notes or an email into tasks').fill('Kick-off\nTODO: order badges');
  await queue.getByRole('button', { name: 'Propose tasks' }).click();
  const proposed = queue.getByRole('listitem').filter({ hasText: 'New task' });
  await expect(proposed.getByLabel('Title')).toHaveValue('order badges');
  await proposed.getByLabel('Title').fill('Order name badges');
  await proposed.getByRole('button', { name: 'Approve' }).click();
  await expect(page.getByText(/^Created /).first()).toBeVisible();
  await expectAccessible(page, 'project digests with suggestions');

  // The assistant is a labelled viewer in the project's people list.
  await page.goto(`/projects/${project.key}`);
  await page.getByRole('button', { name: /People/ }).click();
  await expect(page.getByRole('region', { name: 'Project people' })).toContainText('Project assistant (AI)');
});
