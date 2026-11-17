import { expect, test } from '@playwright/test';
import { capture, hasCredentials, signIn } from './helpers';

test.describe.configure({ mode: 'serial' });

test('the archive finds a checked claim and accepts feedback', async ({ page }) => {
  test.skip(!hasCredentials, 'FS_E2E_EMAIL/FS_E2E_PASSWORD are not set');
  await signIn(page);
  await page.goto('/archive');
  // Search the whole archive: this account may not own the earlier checks.
  const mine = page.getByRole('checkbox');
  if (await mine.isChecked()) await mine.uncheck();
  await page.getByRole('searchbox').fill('Berlin');
  await page.getByRole('button', { name: 'Search checked claims' }).click();
  const entry = page.getByRole('link', { name: /Berlin Wall/ }).first();
  await expect(entry).toBeVisible();
  await capture(page, 'archive');
  await entry.click();
  await expect(page.getByRole('heading', { name: 'Version' })).toBeVisible();
  await page.getByRole('button', { name: 'helpful', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('helpful');
  await capture(page, 'claim');
});
