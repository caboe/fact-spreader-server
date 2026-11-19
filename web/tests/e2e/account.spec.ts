import { expect, test } from '@playwright/test';

// The account menu is UI-only, so a contract-shaped session keeps this test independent
// of a live credential and TOTP enrolment.
const SESSION = {
  user: {
    id: 'usr_editor',
    email: 'editor@test.invalid',
    display_name: 'Editor',
    permissions: ['check:run', 'chat:use'],
  },
  csrf_token: 'csrf-test',
  totp_setup_required: false,
};

test('the header shows a sign-in link and no settings when signed out', async ({ page }) => {
  await page.route('**/api/auth/session', (route) =>
    route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ error: { code: 'unauthenticated', message: 'Sign in.' } }),
    }),
  );

  await page.goto('/login');

  const header = page.locator('header');
  await expect(header.getByRole('link', { name: 'Sign in' })).toBeVisible();
  await expect(header.getByRole('button')).toHaveCount(0);
  await expect(header.getByLabel('Language')).toHaveCount(0);
});

test('the account menu holds language, theme and sign-out when signed in', async ({ page }) => {
  let signedOut = false;
  await page.route('**/api/auth/session', (route) =>
    route.fulfill(
      signedOut
        ? {
            status: 401,
            contentType: 'application/json',
            body: JSON.stringify({ error: { code: 'unauthenticated', message: 'Sign in.' } }),
          }
        : {
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(SESSION),
          },
    ),
  );
  await page.route('**/api/auth/logout', (route) => route.fulfill({ status: 204 }));

  await page.goto('/login');

  const header = page.locator('header');
  const trigger = header.getByRole('button', { name: 'Editor' });
  await expect(trigger).toBeVisible();
  await expect(header.getByLabel('Language')).toHaveCount(0);

  await trigger.click();
  const menu = page.locator('#account-menu');
  await expect(menu).toBeVisible();
  await expect(menu.getByLabel('Language')).toBeVisible();
  await expect(menu.getByRole('group', { name: 'Theme' })).toBeVisible();
  await expect(menu.getByRole('button', { name: 'Sign out' })).toBeVisible();

  await menu.getByRole('button', { name: 'Dark' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');

  await menu.getByLabel('Language').selectOption('de');
  await expect(page.getByRole('heading', { name: 'Anmelden' })).toBeVisible();
  await expect(menu.getByLabel('Sprache')).toBeVisible();
  await expect(menu.getByRole('button', { name: 'Abmelden' })).toBeVisible();

  await page.keyboard.press('Escape');
  await expect(menu).toHaveCount(0);
  await expect(trigger).toBeFocused();

  await trigger.click();
  signedOut = true;
  await page.locator('#account-menu').getByRole('button', { name: 'Abmelden' }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(header.getByRole('link', { name: 'Anmelden' })).toBeVisible();
});
