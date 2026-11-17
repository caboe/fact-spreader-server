import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { capture, hasCredentials, signIn } from './helpers';

test('the chat screen renders and is accessible', async ({ page }) => {
  test.skip(!hasCredentials, 'FS_E2E_EMAIL/FS_E2E_PASSWORD are not set');
  await signIn(page);
  await page.goto('/chat');
  await expect(page.getByRole('heading', { name: 'Chat with the check' })).toBeVisible();
  await expect(page.locator('textarea')).toBeVisible();
  const axe = await new AxeBuilder({ page }).analyze();
  const serious = axe.violations.filter(
    (violation) => violation.impact === 'serious' || violation.impact === 'critical',
  );
  expect(serious, JSON.stringify(serious.map((item) => item.id))).toEqual([]);
  await capture(page, 'chat');
});
