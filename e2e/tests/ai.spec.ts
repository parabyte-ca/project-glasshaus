import { expect, test } from '@playwright/test';

import { api, expectAccessible, makeProject } from './helpers';

// Needs a stack with GLASSHAUS_AI_PROVIDER=fake (CI sets it); skipped otherwise.
test.describe('AI assistant (fake provider)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    const status = await (await api(page))<{ provider: string }>('GET', '/api/v1/ai/status');
    test.skip(status.provider !== 'fake', 'run the stack with GLASSHAUS_AI_PROVIDER=fake');
  });

  test.afterAll(async ({ browser }) => {
    const page = await browser.newPage({ storageState: '.auth/admin.json' });
    await page.goto('/');
    await (await api(page))('PATCH', '/api/v1/admin/settings', { ai_enabled: false });
    await page.close();
  });

  test('admin turns it on; people draft tasks, write updates, review risks and ask', async ({ page }) => {
    await page.goto('/admin?tab=ai');
    const toggle = page.getByLabel('Turn on the AI assistant for this organization');
    await toggle.check();
    const features = [/Status updates/, /Task drafting/, /Risk flags/, /Ask in plain words/, /Questions about reports/];
    for (const label of features) {
      await page.getByLabel(label).check();
    }
    await page.getByRole('button', { name: 'Save AI settings' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Saved' })).toBeVisible();

    const project = await makeProject(page, 'Assisted');
    await page.goto(`/projects/${project.key}`);
    await page.getByRole('button', { name: 'Assistant' }).click();
    const assistant = page.getByRole('region', { name: 'Assistant' });

    await assistant.getByRole('tab', { name: 'Draft tasks' }).click();
    await assistant.getByLabel('What needs doing?').fill('Move the website to new hosting');
    await assistant.getByRole('button', { name: 'Draft tasks' }).click();
    await assistant.getByRole('button', { name: /^Add task: / }).first().click();
    await expect(assistant.getByText('Added')).toBeVisible();
    await expect(page.getByText('Example title').first()).toBeVisible();

    await assistant.getByRole('tab', { name: 'Status update' }).click();
    await assistant.getByRole('button', { name: 'Write status update' }).click();
    await expect(assistant.getByRole('heading', { name: 'Example headline' })).toBeVisible();

    await assistant.getByRole('tab', { name: 'Risks' }).click();
    await assistant.getByRole('button', { name: 'Review risks' }).click();
    await expect(assistant.getByText(/Next step:/).first()).toBeVisible();

    await page.keyboard.press('ControlOrMeta+k');
    const palette = page.getByRole('dialog', { name: 'Command palette' });
    await palette.getByRole('combobox').fill('what is overdue');
    await palette.getByRole('option', { name: /Ask: “what is overdue”/ }).click();
    await expect(palette.getByText(/found/)).toBeVisible();

    await page.goto('/reports');
    await page.getByLabel('Question', { exact: true }).fill('How many open tasks are there?');
    await page.getByRole('button', { name: 'Ask', exact: true }).click();
    await expect(page.getByText('Example answer')).toBeVisible();
    await expectAccessible(page, 'report answer');
    await page.getByRole('link', { name: 'Open in the report builder' }).click();
    await expect(page.getByRole('heading', { name: 'New report', level: 1 })).toBeVisible();
    await expect(page.getByLabel('Name', { exact: true })).toHaveValue('How many open tasks are there?');

    const audit = await (await api(page))<{ action: string }[]>('GET', '/api/v1/audit-log?action=ai.drafting');
    expect(audit.length).toBeGreaterThan(0);
  });
});
