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

// Trusted follow-ups: allowed by the organization and the project, posted on their own, undone by a person.
test('project assistant posts a trusted follow-up and it can be undone', async ({ page }) => {
  await page.goto('/');
  const project = await makeProject(page, 'Trusted');
  const call = await api(page);
  const me = await call<{ id: string }>('GET', '/api/v1/users/me');
  const late = new Date(Date.now() - 2 * 86_400_000).toISOString().slice(0, 10);
  const task = await call<{ id: string; key: string }>('POST', '/api/v1/tasks', {
    project_id: project.id,
    title: 'Pay the supplier',
    due_date: late,
    assignee_id: me.id,
  });
  await call('PATCH', '/api/v1/admin/settings', { assistant_trusted: ['comment'] });
  try {
    await page.goto(`/projects/${project.key}/assistant`);
    await page.getByRole('button', { name: 'Turn on' }).click();
    await expect(page.getByText(/^On\. Next digest/)).toBeVisible();
    await page.getByRole('checkbox', { name: /Post follow-up comments without approval/ }).check();
    const saved = page.waitForResponse(
      (r) => r.request().method() === 'PUT' && r.url().endsWith(`/projects/${project.id}/assistant`),
    );
    await page.getByRole('button', { name: 'Save' }).click();
    expect((await saved).status()).toBe(200);
    await page.getByRole('button', { name: 'Write a digest now' }).click();

    const done = page.getByRole('list', { name: 'Done on its own' });
    await expect(done).toContainText(`Posted automatically on ${task.key}`);
    await expectAccessible(page, 'digests with automatic follow-ups');
    await done.getByRole('button', { name: `Undo the follow-up on ${task.key}` }).click();
    await expect(page.getByText('Follow-up removed')).toBeVisible();
    const comments = await call<{ body: string }[]>('GET', `/api/v1/tasks/${task.id}/comments`);
    expect(comments.filter((c) => c.body.includes('Posted automatically'))).toHaveLength(0);
  } finally {
    await call('PATCH', '/api/v1/admin/settings', { assistant_trusted: [] });
  }
});
