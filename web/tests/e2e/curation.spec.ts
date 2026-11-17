import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { capture } from './helpers';

const SESSION = {
  user: {
    id: 'usr_operator',
    email: 'operator@test.invalid',
    display_name: 'Operator',
    permissions: ['config:manage', 'users:manage', 'usage:read'],
  },
  csrf_token: 'csrf-test',
  totp_setup_required: false,
};

const PUBLISHERS = {
  version: 'shipped-1',
  effective_version: 'local-2',
  entries: [
    { key: 'publisher:test-institute', publisher: 'Test Institute', grade: 'B', disputed: false, overridden: false },
    { key: 'publisher:tabloid', publisher: 'Daily Tabloid', grade: 'D', disputed: true, overridden: true },
  ],
  overrides: [{ key: 'publisher:tabloid', grade: 'D', disputed: true, note: 'known' }],
};

const PERSONAS = [
  {
    id: 'factcheck:analyst',
    name: 'Analyst',
    version: 1,
    enabled: true,
    custom: false,
    overridden: false,
    address_mode: 'direct',
    tone: 'calm',
    didactics: 'answer',
    moral_framing: false,
    verdict_in_text: false,
    substance_display: 'expanded',
    max_words: 180,
    rules: [],
    forbidden: [],
    checks: [],
    test_issues: [],
  },
  {
    id: 'custom:teacher',
    name: 'Teacher',
    version: 1,
    enabled: true,
    custom: true,
    overridden: true,
    address_mode: 'direct',
    tone: 'didactic',
    didactics: 'socratic',
    moral_framing: false,
    verdict_in_text: false,
    substance_display: 'expanded',
    max_words: 220,
    rules: [],
    forbidden: [],
    checks: [],
    test_issues: [],
  },
];

const METHODOLOGY = {
  patterns_version: 'patterns-1',
  version: 2,
  checklists: [
    {
      topic: 'housing',
      name: 'Housing',
      version: 1,
      staleness_days: 365,
      confounders: [{ id: 'rent_control', label: 'Rent control', retrieval_hint: 'rent control' }],
    },
  ],
  patterns: [
    { id: 'cherry_picking', name: 'Cherry picking', definition: 'Selects favourable data.', mechanism: 'Selection bias.' },
  ],
  overrides: {},
};

const INSTANCE = {
  instance_id: 'ins_test',
  name: 'Fact Spreader',
  setup_complete: true,
  corpus_version: 'v1',
  document_count: 1,
  supported_response_languages: ['en', 'de', 'fr', 'es'],
  supported_corpus_languages: ['en', 'de'],
  languages: ['en', 'de'],
};

async function mockApi(page: Page): Promise<{ bodies: Record<string, string[]> }> {
  const bodies: Record<string, string[]> = { publishers: [], personas: [], checklists: [] };
  await page.route('**/api/auth/session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION) }),
  );
  await page.route('**/v1/config/publishers/diff', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { key: 'publisher:tabloid', publisher: 'Daily Tabloid', field: 'grade', shipped: 'C', local: 'D' },
      ]),
    }),
  );
  await page.route('**/v1/config/publishers**', async (route) => {
    if (route.request().method() === 'PUT') {
      bodies.publishers?.push(route.request().postData() ?? '');
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PUBLISHERS) });
  });
  await page.route('**/v1/config/personas**', async (route) => {
    if (route.request().method() === 'PUT') {
      bodies.personas?.push(route.request().postData() ?? '');
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...PERSONAS[0], tone: 'warm' }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PERSONAS) });
  });
  await page.route('**/v1/config/methodology**', async (route) => {
    if (route.request().method() === 'PUT') {
      bodies.checklists?.push(route.request().postData() ?? '');
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(METHODOLOGY) });
  });
  await page.route('**/v1/instance', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(INSTANCE) }),
  );
  await page.route('**/v1/config/moderation-test', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ backend: 'deepseek-flash', flagged: false, categories: [] }),
    }),
  );
  return { bodies };
}

test('settings save and reload and the moderation console reports a pass', async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto('/admin/curation');
  await expect(page.getByRole('heading', { name: 'Curation settings' })).toBeVisible();
  await expect(page.getByText('Test Institute')).toBeVisible();
  await expect(page.getByText('Daily Tabloid')).toBeVisible();
  await expect(page.getByText('Argument patterns')).toBeVisible();

  await page.getByLabel('Grade Test Institute').selectOption('C');
  await page.getByRole('button', { name: 'Save publisher overrides' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Publisher overrides saved.' })).toBeVisible();
  expect(calls.bodies.publishers?.[0]).toContain('"grade":"C"');

  await page.getByRole('button', { name: 'Run moderation test' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Passed: the benign sample is not flagged.' })).toBeVisible();

  await page.getByLabel('Tone Analyst').fill('warm');
  await page.getByRole('row', { name: /Analyst/ }).getByRole('button', { name: 'Save' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Analyst saved.' })).toBeVisible();

  await page.getByLabel('Staleness (days) Housing').fill('300');
  await page.getByRole('row', { name: /Housing/ }).getByRole('button', { name: 'Save' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Housing saved.' })).toBeVisible();

  const axe = await new AxeBuilder({ page }).analyze();
  const serious = axe.violations.filter(
    (violation) => violation.impact === 'serious' || violation.impact === 'critical',
  );
  expect(serious, JSON.stringify(serious.map((item) => item.id))).toEqual([]);
});

test('the curation screen has wide, dark and narrow captures', async ({ page }) => {
  await mockApi(page);
  await page.goto('/admin/curation');
  await expect(page.getByRole('heading', { name: 'Curation settings' })).toBeVisible();
  await capture(page, 'admin-curation', '../docs/screenshots/phase-8');
});
