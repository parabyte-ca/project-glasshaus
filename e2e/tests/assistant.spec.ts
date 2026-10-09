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

  // The assistant is a labelled viewer in the project's people list.
  await page.goto(`/projects/${project.key}`);
  await page.getByRole('button', { name: /People/ }).click();
  await expect(page.getByRole('region', { name: 'Project people' })).toContainText('Project assistant (AI)');
});
