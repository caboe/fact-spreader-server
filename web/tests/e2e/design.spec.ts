import { expect, test } from '@playwright/test';
import { capture, hasCredentials, signIn } from './helpers';

// Design captures must not spend model budget: they reuse an existing report when
// FS_E2E_REPORT_JOB is set and otherwise capture only screens that need no check.
test('capture the design screens', async ({ page }) => {
  test.skip(!hasCredentials, 'FS_E2E_EMAIL/FS_E2E_PASSWORD are not set');
  await signIn(page);
  await capture(page, 'check');
  await page.goto('/chat');
  await expect(page.getByRole('heading', { name: 'Chat with the check' })).toBeVisible();
  await capture(page, 'chat');
  await page.goto('/archive');
  await page.getByRole('searchbox').fill('Berlin');
  await page.getByRole('button', { name: 'Search checked claims' }).click();
  await expect(page.getByRole('link', { name: /Berlin Wall/ }).first()).toBeVisible();
  await capture(page, 'archive');
  await page.getByRole('link', { name: /Berlin Wall/ }).first().click();
  await expect(page.getByRole('heading', { name: 'Version' })).toBeVisible();
  await capture(page, 'claim');

  const jobId = process.env.FS_E2E_REPORT_JOB;
  if (jobId) {
    await page.goto(`/report/${jobId}`);
    await expect(page.getByRole('heading', { name: 'Report' })).toBeVisible();
    await expect(page.locator('#verdict-heading')).not.toBeEmpty();
    await capture(page, 'report');
  }
});
