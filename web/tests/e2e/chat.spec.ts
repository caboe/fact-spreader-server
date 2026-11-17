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

test('a chat message streams a checked answer', async ({ page }) => {
  test.skip(!hasCredentials, 'FS_E2E_EMAIL/FS_E2E_PASSWORD are not set');
  await signIn(page);
  await page.goto('/chat');
  await page.locator('textarea').fill('The Berlin Wall fell in 1989.');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByRole('link', { name: 'Open the full report' })).toBeVisible({
    timeout: 120_000,
  });
  const answer = page.locator('.message:not(.user) .content').last();
  await expect(answer).not.toBeEmpty();
});
