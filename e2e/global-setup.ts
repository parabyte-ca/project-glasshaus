import { chromium, type FullConfig } from '@playwright/test';

import { adminEmail, adminPassword, signIn } from './tests/helpers';

/** Sign in once as the administrator and save the session for every test. */
export default async function globalSetup(config: FullConfig) {
  const use = config.projects[0]!.use;
  const browser = await chromium.launch({ executablePath: process.env.E2E_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ baseURL: use.baseURL });
  await signIn(page, adminEmail, adminPassword());
  await page.context().storageState({ path: '.auth/admin.json' });
  await browser.close();
}
