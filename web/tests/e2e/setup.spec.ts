import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { capture } from './helpers';

const SESSION = {
  user: {
    id: 'usr_admin',
    email: 'admin@test.invalid',
    display_name: 'Admin',
    permissions: ['config:manage', 'users:manage'],
  },
  csrf_token: 'csrf-test',
  totp_setup_required: false,
};

function statusObject() {
  return {
    started: false,
    complete: false,
    setup_token_required: true,
    steps: {
      admin: false,
      totp: false,
      organization: false,
      provider: false,
      models: false,
      moderation: false,
    },
    next_step: 'admin' as string | null,
    instance: null,
  };
}

interface SetupMock {
  status: ReturnType<typeof statusObject>;
  completed: boolean;
}

async function mockSetup(page: Page, signedIn: boolean): Promise<SetupMock> {
  const state: SetupMock = { status: statusObject(), completed: false };
  await page.route('**/api/auth/session', (route) => {
    if (signedIn) {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION) });
    } else {
      route.fulfill({ status: 401, contentType: 'application/json', body: '{}' });
    }
  });
  await page.route('**/api/setup/status', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(state.status) }),
  );
  await page.route('**/api/setup/admin', async (route) => {
    state.status.steps.admin = true;
    state.status.next_step = 'totp';
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        user_id: 'usr_new',
        email: 'admin@test.invalid',
        totp_secret: 'JBSWY3DPEHPK3PXP',
        provisioning_uri: 'otpauth://totp/Fact%20Spreader:admin@test.invalid?secret=JBSWY3DPEHPK3PXP',
      }),
    });
  });
  await page.route('**/api/setup/admin/totp', async (route) => {
    state.status.steps.totp = true;
    state.status.next_step = 'organization';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ recovery_codes: ['fc-rec-one', 'fc-rec-two'] }),
    });
  });
  await page.route('**/api/setup/organization', async (route) => {
    state.status.steps.organization = true;
    state.status.next_step = 'provider';
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(state.status) });
  });
  await page.route('**/api/setup/provider', async (route) => {
    state.status.steps.provider = true;
    state.status.next_step = 'models';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ provider_id: 'prv_new', models: ['deepseek-flash', 'bge-m3'], tested_at: '2026-11-17T10:00:00Z' }),
    });
  });
  await page.route('**/api/setup/models', async (route) => {
    state.status.steps.models = true;
    state.status.next_step = 'moderation';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ aliases: ['fs-chat'], chat_model: 'deepseek-flash', embedding_model: 'bge-m3' }),
    });
  });
  await page.route('**/api/setup/moderation-test', async (route) => {
    state.status.steps.moderation = true;
    state.status.next_step = null;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ backend: 'deepseek-flash', flagged: false, categories: [] }),
    });
  });
  await page.route('**/api/setup/complete', async (route) => {
    state.completed = true;
    state.status.complete = true;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ complete: true, instance_id: 'inst_new' }),
    });
  });
  return state;
}

test('the wizard creates the admin, shows the TOTP secret and recovery codes', async ({ page }) => {
  await mockSetup(page, false);
  await page.goto('/setup');
  await expect(page.getByRole('heading', { name: 'Set up Fact Spreader' })).toBeVisible();
  await page.getByLabel('Setup token').fill('setup-token');
  await page.getByLabel('Email').fill('admin@test.invalid');
  await page.getByLabel('Password').fill('Correct-horse-2026!');
  await page.getByLabel('Display name').fill('Admin');
  await page.getByRole('button', { name: 'Create administrator' }).click();
  await expect(page.getByText('JBSWY3DPEHPK3PXP', { exact: true })).toBeVisible();
  await page.getByLabel('Authenticator code').fill('123456');
  await page.getByRole('button', { name: 'Confirm TOTP' }).click();
  await expect(page.getByText('fc-rec-one')).toBeVisible();
  await expect(page.getByText('fc-rec-two')).toBeVisible();
});

test('the remaining wizard steps run to completion', async ({ page }) => {
  const state = await mockSetup(page, true);
  state.status.steps.admin = true;
  state.status.steps.totp = true;
  state.status.next_step = 'organization';
  await page.goto('/setup');
  await page.getByLabel('Instance name').fill('Fact Spreader Test');
  await page.getByLabel('Organization').fill('Test Org');
  await page.getByLabel('Monthly budget (USD)').fill('15');
  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByLabel('Provider name')).toBeVisible();

  await page.getByLabel('Provider name').fill('deepseek');
  await page.getByLabel('Base URL').fill('https://api.deepseek.com/v1');
  await page.getByLabel('API key').fill('sk-test');
  await page.getByRole('button', { name: 'Test connection' }).click();
  await expect(page.getByRole('status').filter({ hasText: '2 models answered.' })).toBeVisible();

  await page.getByLabel('Chat model').fill('deepseek-flash');
  await page.getByLabel('Embedding model').fill('bge-m3');
  await page.getByLabel('Embedding dimensions').fill('1024');
  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByRole('button', { name: 'Run moderation test' })).toBeVisible();

  await page.getByRole('button', { name: 'Run moderation test' }).click();
  await expect(page.getByText('Moderation passed.')).toBeVisible();
  await page.getByRole('button', { name: 'Complete setup' }).click();
  await expect.poll(() => state.completed).toBe(true);

  const axe = await new AxeBuilder({ page }).analyze();
  const serious = axe.violations.filter(
    (violation) => violation.impact === 'serious' || violation.impact === 'critical',
  );
  expect(serious, JSON.stringify(serious.map((item) => item.id))).toEqual([]);
});

test('the setup screen has wide, dark and narrow captures', async ({ page }) => {
  const state = await mockSetup(page, true);
  state.status.steps.admin = true;
  state.status.steps.totp = true;
  state.status.next_step = 'organization';
  await page.goto('/setup');
  await expect(page.getByRole('heading', { name: 'Set up Fact Spreader' })).toBeVisible();
  await capture(page, 'setup', '../docs/screenshots/phase-8');
});
