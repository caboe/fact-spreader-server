import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { capture } from './helpers';

// The admin UI is exercised with contract-shaped fixtures so the test needs no TOTP
// credential and spends no model budget. The endpoints themselves have integration tests.
const SESSION = {
  user: {
    id: 'usr_test',
    email: 'operator@test.invalid',
    display_name: 'Operator',
    permissions: ['config:manage', 'users:manage', 'usage:read'],
  },
  csrf_token: 'csrf-test',
  totp_setup_required: false,
};

const PROVIDERS = [
  {
    id: 'prv_1',
    name: 'deepseek',
    base_url: 'https://api.deepseek.com/v1',
    is_local: false,
    enabled: true,
    has_key: true,
    created_at: '2026-11-17T00:00:00Z',
  },
];

const MODELS = [
  {
    id: 'mdl_1',
    provider_id: 'prv_1',
    model_name: 'deepseek-flash',
    gateway_alias: null,
    source_model_id: null,
    capabilities: ['chat', 'structured_output'],
    tested_capabilities: ['chat', 'structured_output'],
    context_window: 128000,
    embedding_dim: null,
    multilingual: false,
    is_local: false,
    enabled: true,
    input_cost_per_mtok: 0.3,
    output_cost_per_mtok: 0.5,
    created_at: '2026-11-17T00:00:00Z',
  },
  {
    id: 'mdl_2',
    provider_id: 'prv_1',
    model_name: 'bge-m3',
    gateway_alias: null,
    source_model_id: null,
    capabilities: ['embedding'],
    tested_capabilities: ['embedding'],
    context_window: 8192,
    embedding_dim: 1024,
    multilingual: true,
    is_local: true,
    enabled: true,
    input_cost_per_mtok: 0,
    output_cost_per_mtok: 0,
    created_at: '2026-11-17T00:00:00Z',
  },
];

const ROLES = [
  {
    alias: 'fs-extract',
    label: 'extraction',
    required_capabilities: ['chat', 'structured_output'],
    min_context: 8192,
    multilingual: false,
    embedding_dim: null,
    model: MODELS[0],
    suitable: true,
    reasons: [],
  },
  {
    alias: 'fs-audit',
    label: 'audit',
    required_capabilities: ['chat', 'structured_output'],
    min_context: 8192,
    multilingual: true,
    embedding_dim: null,
    model: MODELS[0],
    suitable: false,
    reasons: ['not_multilingual'],
  },
  {
    alias: 'fs-embedding',
    label: 'corpus embeddings',
    required_capabilities: ['embedding'],
    min_context: null,
    multilingual: true,
    embedding_dim: 1024,
    model: null,
    suitable: false,
    reasons: ['capability_not_tested:embedding'],
  },
];

const USERS = {
  data: [
    {
      id: 'usr_test',
      email: 'operator@test.invalid',
      display_name: 'Operator',
      roles: ['admin'],
      permissions: [],
      effective_permissions: ['config:manage', 'users:manage', 'usage:read'],
      denied_permissions: [],
      requests_per_day: 500,
      text_chars: 20000,
      max_file_bytes: 20000000,
      max_batch_files: 100,
      is_active: true,
      totp_enabled: true,
    },
  ],
};

const USAGE = {
  period: { from: '2026-11-01', to: '2026-11-17' },
  currency: 'USD',
  totals: { calls: 7, tokens_in: 100, tokens_out: 50, cost_usd: 0.0123 },
  cards: { check: 7 },
  series: [{ date: '2026-11-17', calls: 7, tokens_in: 100, tokens_out: 50, cost_usd: 0.0123 }],
  breakdowns: {
    consumer: [{ key: 'pipeline', calls: 7, tokens_in: 100, tokens_out: 50, cost_usd: 0.0123 }],
    role: [],
    provider: [],
    model: [],
  },
};

test.beforeEach(async ({ page }) => {
  await page.route('**/api/auth/session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION) }),
  );
  await page.route('**/v1/config/providers', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PROVIDERS) }),
  );
  await page.route('**/v1/config/models', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MODELS) }),
  );
  await page.route('**/v1/config/roles**', async (route) => {
    if (route.request().method() === 'PUT') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...ROLES[0], suitable: true, reasons: [], model: MODELS[0] }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ROLES) });
  });
  await page.route('**/v1/users', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(USERS) }),
  );
  await page.route('**/v1/usage/summary?**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(USAGE) }),
  );
  await page.route('**/v1/config/data-flow', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ allow_external: true, fallback_alias: null }),
    }),
  );
  await page.route('**/v1/config/budgets', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ roles: {} }) }),
  );
  await page.route('**/v1/instance', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ document_count: 1 }),
    }),
  );
});

test('the admin overview lists the registry state and passes axe', async ({ page }) => {
  await page.goto('/admin');
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible();
  await expect(page.getByRole('link', { name: /1\s*Providers and models/ })).toBeVisible();
  await expect(page.getByRole('link', { name: /Users/ }).first()).toBeVisible();
  const axe = await new AxeBuilder({ page }).analyze();
  const serious = axe.violations.filter(
    (violation) => violation.impact === 'serious' || violation.impact === 'critical',
  );
  expect(serious, JSON.stringify(serious.map((item) => item.id))).toEqual([]);
});

test('providers, roles, users and usage render the operator data', async ({ page }) => {
  await page.goto('/admin/providers');
  await expect(page.getByText('https://api.deepseek.com/v1')).toBeVisible();
  await expect(page.getByRole('cell', { name: 'deepseek-flash' })).toBeVisible();

  await page.goto('/admin/roles');
  const extract = page.locator('article').filter({ has: page.getByRole('heading', { name: 'fs-extract' }) });
  await expect(extract).toBeVisible();
  await extract.getByRole('button', { name: 'Assign' }).click();
  await expect(extract.getByRole('status')).toContainText('role assigned');

  const audit = page.locator('article').filter({ has: page.getByRole('heading', { name: 'fs-audit' }) });
  await expect(audit.getByText('The model is not marked multilingual.')).toBeVisible();
  await expect(audit.getByRole('button', { name: 'Assign' })).toBeDisabled();
  await expect(audit.getByText('No model has the required capabilities tested yet.')).toBeVisible();
  await page.getByLabel('Show unsuitable models').check();
  const auditOption = audit.locator('option', { hasText: 'not marked multilingual' });
  await expect(auditOption).toBeDisabled();
  await page.getByLabel('Show unsuitable models').uncheck();
  await expect(auditOption).toHaveCount(0);

  // The form used to preselect the first base model, so every card offered the chat
  // model. The embedding card must preselect the tested embedding model instead.
  const embedding = page.locator('article').filter({ has: page.getByRole('heading', { name: 'fs-embedding' }) });
  await expect(embedding.locator('select')).toHaveValue('mdl_2');
  await expect(embedding.getByRole('button', { name: 'Assign' })).toBeEnabled();

  await page.goto('/admin/users');
  await expect(page.getByText('operator@test.invalid').first()).toBeVisible();
  await expect(page.getByRole('cell', { name: 'admin' })).toBeVisible();

  await page.goto('/admin/usage');
  await expect(page.getByText('$0.0123')).toBeVisible();
  await expect(page.getByText('pipeline')).toBeVisible();
});

test('settings expose the data-flow policy and re-index stays disabled until confirmed', async ({
  page,
}) => {
  await page.goto('/admin/settings');
  await expect(page.getByRole('heading', { name: 'Data-flow policy' })).toBeVisible();
  await expect(page.getByRole('checkbox')).toBeChecked();
  await page.goto('/admin/reindex');
  const start = page.getByRole('button', { name: 'Start re-index' });
  await expect(start).toBeDisabled();
  await page.getByRole('checkbox').check();
  await expect(start).toBeEnabled();
});


test('the admin screens have wide, dark and narrow captures', async ({ page }) => {
  const screens: [string, string][] = [
    ['/admin', 'admin-overview'],
    ['/admin/providers', 'admin-providers'],
    ['/admin/roles', 'admin-roles'],
    ['/admin/users', 'admin-users'],
    ['/admin/usage', 'admin-usage'],
    ['/admin/settings', 'admin-settings'],
    ['/admin/reindex', 'admin-reindex'],
  ];
  for (const [path, name] of screens) {
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await capture(page, name, '../docs/screenshots/phase-8');
  }
});
