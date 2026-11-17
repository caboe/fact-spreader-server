import { expect, test } from '@playwright/test';
import { email, hasCredentials, password } from './helpers';
import { totp } from './totp';

// Run only after an operator TOTP reset (FS_E2E_TOTP_SETUP=1): the test enrols a new
// secret and would invalidate the credential used by the other suites.
test('a privileged account can re-enrol TOTP through the UI', async ({ page }) => {
  test.skip(!hasCredentials || process.env.FS_E2E_TOTP_SETUP !== '1', 'TOTP setup not requested');
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/totp$/);
  await expect(page.getByText('Two-factor authentication is required')).toBeVisible();
  await page.getByRole('button', { name: 'Generate secret' }).click();
  const secret = (await page.locator('code.secret').innerText()).replace(/\s/g, '');
  expect(secret.length).toBeGreaterThan(15);
  await page.getByLabel('Code from the app').fill(totp(secret));
  await page.getByRole('button', { name: 'Confirm' }).click();
  await expect(page.getByText('Save these recovery codes')).toBeVisible();
  await expect(page.locator('.codes code')).toHaveCount(8);
});
