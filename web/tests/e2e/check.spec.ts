import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { capture, hasCredentials, signIn } from './helpers';

test.describe.configure({ mode: 'serial' });

test('the check screen is accessible, localized and fits a narrow viewport', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Check a claim' })).toBeVisible();

  const axe = await new AxeBuilder({ page }).analyze();
  const serious = axe.violations.filter(
    (violation) => violation.impact === 'serious' || violation.impact === 'critical',
  );
  expect(serious, JSON.stringify(serious.map((item) => item.id))).toEqual([]);

  await page.locator('.language select').selectOption('de');
  await expect(page.getByRole('heading', { name: 'Aussage prüfen' })).toBeVisible();
  await page.locator('.language select').selectOption('fr');
  await expect(page.getByRole('heading', { name: 'Vérifier une affirmation' })).toBeVisible();
  await page.locator('.language select').selectOption('es');
  await expect(page.getByRole('heading', { name: 'Comprobar una afirmación' })).toBeVisible();
  await page.locator('.language select').selectOption('en');

  await page.setViewportSize({ width: 360, height: 800 });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);

  await capture(page, 'check');
});

test('a real check runs from the browser to the report', async ({ page }) => {
  test.skip(!hasCredentials, 'FS_E2E_EMAIL/FS_E2E_PASSWORD are not set');
  await signIn(page);
  await page.locator('textarea').first().fill('The Berlin Wall fell in 1989.');
  await page.getByRole('button', { name: 'Check', exact: true }).click();
  await page.waitForURL(/\/report\//, { timeout: 90_000 });
  await expect(page.getByRole('heading', { name: 'Report' })).toBeVisible();
  await expect(page.locator('#verdict-heading')).not.toBeEmpty();
  await expect(page.getByRole('heading', { name: 'Deterministic report' })).toBeVisible();
  await capture(page, 'report');
});


test('a file check runs from the UI', async ({ page }) => {
  test.skip(!hasCredentials, 'FS_E2E_EMAIL/FS_E2E_PASSWORD are not set');
  await signIn(page);
  await page.getByRole('button', { name: 'File', exact: true }).click();
  await page.locator('input[type=file]').setInputFiles('tests/fixtures/claim.md');
  await page.getByRole('button', { name: 'Check', exact: true }).click();
  await page.waitForURL(/\/report\//, { timeout: 90_000 });
  await expect(page.getByRole('heading', { name: 'Report' })).toBeVisible();
});

test('an image check runs from the UI', async ({ page }) => {
  test.skip(!hasCredentials, 'FS_E2E_EMAIL/FS_E2E_PASSWORD are not set');
  await signIn(page);
  await page.getByRole('button', { name: 'Image', exact: true }).click();
  await page.locator('input[type=file]').setInputFiles('tests/fixtures/claim.png');
  await page.getByRole('button', { name: 'Check', exact: true }).click();
  await page.waitForURL(/\/report\//, { timeout: 120_000 });
  await expect(page.getByRole('heading', { name: 'Report' })).toBeVisible();
});

test('a URL check runs from the UI', async ({ page }) => {
  test.skip(!hasCredentials, 'FS_E2E_EMAIL/FS_E2E_PASSWORD are not set');
  await signIn(page);
  await page.getByRole('button', { name: 'URL', exact: true }).click();
  await page.getByPlaceholder('https://example.org/article').fill('https://example.com/');
  await page.getByRole('button', { name: 'Check', exact: true }).click();
  await page.waitForURL(/\/report\//, { timeout: 120_000 });
  await expect(page.getByRole('heading', { name: 'Report' })).toBeVisible();
});
