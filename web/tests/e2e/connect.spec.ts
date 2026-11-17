import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { capture } from './helpers';
import { totp } from './totp';

const SESSION = {
  user: {
    id: 'usr_editor',
    email: 'editor@test.invalid',
    display_name: 'Editor',
    permissions: ['documents:submit', 'devices:manage', 'claims:submit'],
  },
  csrf_token: 'csrf-test',
  totp_setup_required: false,
};

const DEVICES = {
  data: [
    {
      id: 'dev_one',
      name: 'Firefox on macOS',
      permissions: ['claims:submit'],
      created_at: '2026-11-17T10:00:00Z',
      last_seen_at: null,
      revoked_at: null,
    },
  ],
};

test('the connect screen creates, shows and revokes a device token', async ({ page }) => {
  let revoked = '';
  await page.route('**/api/auth/session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION) }),
  );
  await page.route('**/v1/devices', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          device: { ...DEVICES.data[0], id: 'dev_new', name: 'Chrome on Linux' },
          token: 'fc_dev_testtoken',
        }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(DEVICES.data) });
  });
  await page.route(/\/v1\/devices\/dev_one$/, async (route) => {
    revoked = route.request().method();
    await route.fulfill({ status: 204 });
  });

  await page.goto('/connect');
  await expect(page.getByRole('heading', { name: 'Connect the plugin' })).toBeVisible();
  await expect(page.getByText('Firefox on macOS')).toBeVisible();
  await page.getByLabel('Device name').fill('Chrome on Linux');
  await page.getByRole('button', { name: 'Create token' }).click();
  await expect(page.getByText('fc_dev_testtoken')).toBeVisible();
  await expect(page.getByText('Device created. Copy the token now.')).toBeVisible();

  page.on('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Revoke' }).click();
  await expect.poll(() => revoked).toBe('DELETE');

  const axe = await new AxeBuilder({ page }).analyze();
  const serious = axe.violations.filter(
    (violation) => violation.impact === 'serious' || violation.impact === 'critical',
  );
  expect(serious, JSON.stringify(serious.map((item) => item.id))).toEqual([]);
});

test('the connect screen has wide, dark and narrow captures', async ({ page }) => {
  await page.route('**/api/auth/session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION) }),
  );
  await page.route('**/v1/devices', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(DEVICES.data) }),
  );
  await page.goto('/connect');
  await expect(page.getByRole('heading', { name: 'Connect the plugin' })).toBeVisible();
  await capture(page, 'connect', '../docs/screenshots/phase-8');
});

const email = process.env.FS_E2E_EDITOR_EMAIL ?? '';
const password = process.env.FS_E2E_EDITOR_PASSWORD ?? '';
const secret = process.env.FS_E2E_EDITOR_TOTP ?? '';

test('live: a device token submits a compact check and revocation stops it', async ({ page }) => {
  test.skip(!email || !password || !secret, 'editor E2E is not configured');
  test.setTimeout(180_000);
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByLabel(/TOTP/).fill(totp(secret));
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('heading', { name: 'Check a claim' })).toBeVisible();

  await page.goto('/connect');
  await page.getByLabel('Device name').fill('E2E compact device');
  await page.getByRole('button', { name: 'Create token' }).click();
  const token = (await page.locator('.secret code').textContent())?.trim() ?? '';
  expect(token.startsWith('fc_dev_')).toBe(true);

  const accepted = await page.request.post('/v1/factcheck', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      input: { type: 'text', text: 'The Berlin Wall fell in 1989.' },
      output_format: 'compact',
      mode: 'async',
    },
  });
  expect(accepted.status()).toBe(202);
  const job = (await accepted.json()) as { job: { id: string } };
  let compact: { verdict: string } | null = null;
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const envelope = await page.request.get(`/v1/factcheck/${job.job.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = (await envelope.json()) as {
      job: { state: string };
      result: { compact: { verdict: string } | null } | null;
    };
    if (body.job.state === 'done') {
      compact = body.result?.compact ?? null;
      break;
    }
    if (body.job.state === 'failed') break;
    await page.waitForTimeout(1500);
  }
  expect(compact).not.toBeNull();
  expect(compact?.verdict).toBeTruthy();

  page.on('dialog', (dialog) => dialog.accept());
  await page
    .getByRole('listitem')
    .filter({ hasText: 'E2E compact device' })
    .first()
    .getByRole('button', { name: 'Revoke' })
    .click();
  await expect(page.getByText('Device revoked.')).toBeVisible();
  const after = await page.request.post('/v1/factcheck', {
    headers: { Authorization: `Bearer ${token}` },
    data: { input: { type: 'text', text: 'The Berlin Wall fell in 1989.' } },
  });
  expect(after.status()).toBe(401);
});
