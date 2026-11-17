import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { capture } from './helpers';
import { totp } from './totp';

const SESSION = {
  user: {
    id: 'usr_editor',
    email: 'editor@test.invalid',
    display_name: 'Editor',
    permissions: ['documents:submit', 'documents:review', 'chat:use'],
  },
  csrf_token: 'csrf-test',
  totp_setup_required: false,
};

const BATCH = {
  id: 'bch_test',
  state: 'processing',
  counts: { total: 2, ready: 1, warning: 0, duplicate: 0, failed: 1 },
  estimated_usd: 0.0012,
  actual_usd: 0,
  budget_remaining_usd: 4.5,
  files: [
    {
      document_id: 'doc_ready',
      filename: 'report.md',
      state: 'ready',
      warnings: [],
    },
    {
      document_id: 'doc_failed',
      filename: 'scan.png',
      state: 'failed',
      warnings: [],
    },
  ],
  warnings: [{ code: 'zip_sanitized', message: 'skipped unsafe path' }],
  created_at: '2026-11-17T10:00:00Z',
  updated_at: '2026-11-17T10:00:00Z',
};

async function mockApi(page: Page): Promise<{ submitted: boolean }> {
  const state = { submitted: false };
  await page.route('**/api/auth/session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION) }),
  );
  await page.route('**/v1/documents/batches/estimate', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        estimate_usd: 7.5,
        budget_remaining_usd: 4.5,
        exceeds_budget: true,
        files: [
          { filename: 'report.md', size_bytes: 1200 },
          { filename: 'scan.png', size_bytes: 400 },
        ],
        warnings: [],
      }),
    }),
  );
  await page.route('**/v1/documents/batches', async (route) => {
    if (route.request().method() === 'POST') {
      state.submitted = true;
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({ batch: BATCH }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ batch: BATCH }) });
  });
  await page.route('**/v1/documents/batches/bch_test**', async (route) => {
    const url = route.request().url();
    if (url.endsWith('/retry')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ results: [{ document_id: 'doc_failed', error: 'parse_failed' }] }),
      });
      return;
    }
    if (url.endsWith('/approve')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ results: [{ document_id: 'doc_ready', state: 'approved' }] }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ batch: BATCH }),
    });
  });
  return state;
}

test('a batch shows the estimate, the budget block and per-file states', async ({ page }) => {
  const state = await mockApi(page);
  await page.goto('/submit');
  await expect(page.getByRole('heading', { name: 'Submit documents' })).toBeVisible();

  await page.setInputFiles('#batch-files', [
    { name: 'report.md', mimeType: 'text/markdown', buffer: Buffer.from('# Report') },
    { name: 'scan.png', mimeType: 'image/png', buffer: Buffer.from('png') },
  ]);
  await page.getByRole('button', { name: 'Estimate cost' }).click();
  await expect(page.getByText('Estimated cost')).toBeVisible();
  await expect(page.getByText('Budget remaining')).toBeVisible();
  await expect(page.getByText(/estimate exceeds the remaining monthly budget/i)).toBeVisible();

  await expect(page.getByRole('button', { name: 'Submit batch' })).toBeDisabled();
  expect(state.submitted).toBe(false);
  await page.getByRole('checkbox', { name: 'Accept the overspend' }).check();
  await page.getByRole('button', { name: 'Submit batch' }).click();
  await expect(page.getByRole('heading', { name: /Batch bch_test/ })).toBeVisible();
  expect(state.submitted).toBe(true);

  await expect(page.getByText('report.md')).toBeVisible();
  await expect(page.getByText('scan.png')).toBeVisible();
  await expect(page.getByText('skipped unsafe path')).toBeVisible();
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'doc_failed' })).toBeVisible();

  const axe = await new AxeBuilder({ page }).analyze();
  const serious = axe.violations.filter(
    (violation) => violation.impact === 'serious' || violation.impact === 'critical',
  );
  expect(serious, JSON.stringify(serious.map((item) => item.id))).toEqual([]);
});

test('the batch screen has wide, dark and narrow captures', async ({ page }) => {
  await mockApi(page);
  await page.goto('/submit');
  await page.setInputFiles('#batch-files', [
    { name: 'report.md', mimeType: 'text/markdown', buffer: Buffer.from('# Report') },
  ]);
  await page.getByRole('button', { name: 'Estimate cost' }).click();
  await expect(page.getByText('Estimated cost')).toBeVisible();
  await capture(page, 'submit', '../docs/screenshots/phase-8');
});

const editorEmail = process.env.FS_E2E_EDITOR_EMAIL ?? '';
const editorPassword = process.env.FS_E2E_EDITOR_PASSWORD ?? '';
const editorTotp = process.env.FS_E2E_EDITOR_TOTP ?? '';

test('live: a mixed batch completes, retries and approves', async ({ page }) => {
  test.skip(!editorEmail || !editorPassword || !editorTotp, 'editor E2E is not configured');
  test.setTimeout(180_000);
  const stamp = Date.now().toString(36);
  const title = `Batch live document ${stamp}`;
  const filename = `e2e-batch-${stamp}.md`;
  await page.goto('/login');
  await page.getByLabel('Email').fill(editorEmail);
  await page.getByLabel('Password').fill(editorPassword);
  await page.getByLabel(/TOTP/).fill(totp(editorTotp));
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('heading', { name: 'Check a claim' })).toBeVisible();

  await page.goto('/submit');
  await page.setInputFiles('#batch-files', [
    {
      name: filename,
      mimeType: 'text/markdown',
      buffer: Buffer.from(
        `# ${title}\n\nThe Berlin population grew slightly in 2025. Vacancy stayed low.`,
      ),
    },
    { name: 'e2e-scan.png', mimeType: 'image/png', buffer: Buffer.from('not-an-image') },
  ]);
  await page.getByRole('button', { name: 'Estimate cost' }).click();
  await expect(page.getByText('Estimated cost')).toBeVisible();
  await page.getByRole('button', { name: 'Submit batch' }).click();
  await expect(page.getByRole('heading', { name: /Batch bch_/ })).toBeVisible();

  await expect(page.getByText(filename)).toBeVisible();
  await expect(page.getByText('e2e-scan.png')).toBeVisible();
  await expect(page.locator('.badge.state-failed')).toBeVisible({ timeout: 60_000 });
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'doc_' })).toBeVisible();

  await expect(page.getByRole('checkbox', { name: new RegExp(filename) })).toBeVisible({
    timeout: 60_000,
  });
  await page.getByRole('checkbox', { name: new RegExp(filename) }).check();
  await page.getByRole('checkbox', { name: /I confirm the licence/ }).check();
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '1 documents approved.' })).toBeVisible();

  // Wait for indexing, then withdraw so the corpus ends unchanged.
  await expect
    .poll(
      async () => {
        const response = await page.request.get('/v1/review/queue?state=indexed');
        const body = (await response.json()) as { data: { title: string }[] };
        return body.data.some((item) => item.title === filename);
      },
      { timeout: 90_000 },
    )
    .toBe(true);
  await page.goto('/editorial');
  await page.getByLabel('Show').selectOption('indexed');
  await page.getByRole('button', { name: new RegExp(filename) }).click();
  await page.getByLabel('Reason').fill('E2E cleanup');
  await page.getByRole('button', { name: 'Withdraw' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Withdrawn. New citations stop.' })).toBeVisible();
});
