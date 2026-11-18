import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { capture } from './helpers';
import { totp } from './totp';

// The editorial queue is exercised with contract-shaped fixtures so the test needs no
// TOTP credential; the live approval run is a separate, explicit check.
const SESSION = {
  user: {
    id: 'usr_editor',
    email: 'editor@test.invalid',
    display_name: 'Editor',
    permissions: ['documents:review', 'documents:submit', 'chat:use'],
  },
  csrf_token: 'csrf-test',
  totp_setup_required: false,
};

function document(overrides: Record<string, unknown>) {
  return {
    id: 'doc_1',
    version: 1,
    content_hash: 'hash',
    title: 'Housing costs and inflation',
    publisher: 'Test Institute',
    authors: [],
    publication_date: '2026-01-02',
    url: 'https://example.com/report',
    doi: null,
    dataset_id: null,
    source_quality: 'B',
    source_quality_basis: { grade: 'B' },
    domain_tags: ['housing'],
    language: 'en',
    license: 'CC BY 4.0',
    redistribution: 'metadata_only',
    curator_organization: 'Test Institute',
    origin_instance_id: 'ins_1',
    origin_document_id: 'doc_1',
    provenance_chain: [],
    content_type: 'text/markdown',
    size_bytes: 1200,
    state: 'warning',
    warnings: [{ code: 'single_source', message: 'Only one source supports this figure.' }],
    duplicate_of: null,
    submitted_by: 'usr_editor',
    approval: null,
    figures: [],
    approval_preselected: false,
    created_at: '2026-11-17T10:00:00Z',
    updated_at: '2026-11-17T10:00:00Z',
    deleted: false,
    ...overrides,
  };
}

const FIGURE = {
  id: 'fig_1',
  page: 3,
  number: '1',
  caption: 'Rent index 2015–2025',
  description: 'A line chart of rent prices.',
  editor_checked: false,
};

const WARNING_DOC = document({
  id: 'doc_1',
  title: 'Housing costs and inflation',
  figures: [FIGURE],
});

const PRESELECTED_DOC = document({
  id: 'doc_2',
  title: 'Vacancy rates in Berlin',
  publisher: 'Test Office',
  state: 'ready',
  source_quality: 'C',
  warnings: [],
  approval_preselected: true,
  submitted_by: 'usr_other',
});

async function mockApi(
  page: Page,
  queueDocs: Record<string, unknown>[] = [WARNING_DOC, PRESELECTED_DOC],
): Promise<{ approvals: string[]; patched: string[]; qualities: string[] }> {
  const approvals: string[] = [];
  const patched: string[] = [];
  const qualities: string[] = [];
  await page.route('**/api/auth/session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION) }),
  );
  await page.route('**/v1/review/queue**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: queueDocs,
        counts: { ready: 1, warnings: 1, duplicates: 0, approved: 0, indexed: 1 },
        summary: { total: 2, returned: 2 },
      }),
    }),
  );
  await page.route('**/v1/editor/contradictions**', async (route) => {
    if (route.request().method() === 'PATCH') {
      patched.push(route.request().url());
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"state":"acknowledged"}' });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: [
          {
            id: 'con_1',
            statement_text: 'Rents doubled between 2015 and 2025.',
            result_ids: ['res_1'],
            supporting: [{ result_id: 'res_1', document_id: 'doc_1' }],
            refuting: [{ result_id: 'res_2', document_id: 'doc_2' }],
            state: 'open',
            detected_at: '2026-11-17T09:00:00Z',
          },
        ],
        counts: { total: 1, open: 1 },
      }),
    });
  });
  await page.route('**/v1/editor/gaps**', async (route) => {
    if (route.request().method() === 'POST') {
      patched.push(route.request().url());
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({ jobs: [], skipped_budget: 0 }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: [
          {
            id: 'gap_1',
            normalized_topic: 'social housing',
            query: 'How large is the social housing stock?',
            language: 'en',
            topics: ['housing'],
            frequency: 4,
            sample_result_ids: ['res_1'],
            state: 'open',
            first_seen: '2026-11-10T00:00:00Z',
            last_seen: '2026-11-17T00:00:00Z',
          },
        ],
        counts: { total: 1, open: 1 },
      }),
    });
  });
  await page.route(/\/v1\/documents\/doc_1\/content$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/markdown',
      body: '# Housing report\n\nRent prices rose faster than incomes.',
    }),
  );
  await page.route(/\/v1\/documents\/doc_2\/content$/, (route) =>
    route.fulfill({ status: 200, contentType: 'text/markdown', body: '# Vacancy report' }),
  );
  await page.route(/\/v1\/documents\/doc_\d+$/, async (route) => {
    const base = route.request().url().endsWith('doc_2') ? PRESELECTED_DOC : WARNING_DOC;
    if (route.request().method() === 'PATCH') {
      const body = JSON.parse(route.request().postData() ?? '{}') as { source_quality?: string };
      qualities.push(route.request().postData() ?? '');
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...base, source_quality: body.source_quality ?? base.source_quality }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(base),
    });
  });
  await page.route(/\/v1\/documents\/quality$/, async (route) => {
    const body = JSON.parse(route.request().postData() ?? '{}') as {
      document_ids?: string[];
      source_quality?: string;
    };
    qualities.push(route.request().postData() ?? '');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        results: (body.document_ids ?? []).map((document_id) => ({
          document_id,
          state: 'approved',
          source_quality: body.source_quality,
        })),
      }),
    });
  });
  await page.route(/\/v1\/documents\/doc_\d+\/approve$/, async (route) => {
    approvals.push(route.request().postData() ?? '');
    const id = route.request().url().includes('doc_2') ? 'doc_2' : 'doc_1';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...(id === 'doc_2' ? PRESELECTED_DOC : WARNING_DOC),
        state: 'approved',
        approval_preselected: false,
        approval: { approved_at: '2026-11-17T12:00:00Z', approved_by: 'usr_editor', note: null },
      }),
    });
  });
  await page.route(/\/v1\/documents\/doc_\d+\/figures\/fig_1$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...WARNING_DOC,
        figures: [{ ...FIGURE, description: 'Corrected chart', editor_checked: true }],
      }),
    }),
  );
  return { approvals, patched, qualities };
}

test('an editor reviews, corrects and approves documents', async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto('/editorial');
  await expect(page.getByRole('heading', { name: 'Editorial queue' })).toBeVisible();
  await expect(page.getByRole('button', { name: /Housing costs and inflation/ })).toBeVisible();
  await expect(page.getByText('Only one source supports this figure.')).toBeVisible();

  await page.getByRole('button', { name: /Housing costs and inflation/ }).click();
  await expect(page.getByRole('heading', { name: 'Housing costs and inflation' })).toBeVisible();
  await expect(page.getByText('Rent prices rose faster than incomes.')).toBeVisible();

  await page.getByLabel('Description').fill('Corrected chart');
  await page.getByRole('button', { name: 'Save description' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Figure description saved.' })).toBeVisible();

  await page.getByRole('checkbox', { name: /I confirm the licence/ }).check();
  const detailQuality = page.locator('.detail').getByLabel('Source quality');
  await expect(page.getByRole('button', { name: 'Approve', exact: true })).toBeDisabled();
  await detailQuality.selectOption('B');
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Approved. Indexing started.' })).toBeVisible();
  expect(calls.approvals[0]).toContain('"license_confirmed":true');
  expect(calls.approvals[0]).toContain('"source_quality":"B"');

  await page.getByRole('tab', { name: /Contradictions/ }).click();
  await expect(page.getByText('Rents doubled between 2015 and 2025.')).toBeVisible();
  await page.getByRole('button', { name: 'Acknowledge' }).click();
  await expect.poll(() => calls.patched.length).toBeGreaterThan(0);

  await page.getByRole('tab', { name: /Corpus gaps/ }).click();
  await expect(page.getByText('How large is the social housing stock?')).toBeVisible();
  await page.getByRole('button', { name: 'Recheck' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Rechecks queued: 0' })).toBeVisible();

  const axe = await new AxeBuilder({ page }).analyze();
  const serious = axe.violations.filter(
    (violation) => violation.impact === 'serious' || violation.impact === 'critical',
  );
  expect(serious, JSON.stringify(serious.map((item) => item.id))).toEqual([]);
});

test('an editor selects all documents and applies a mixed source quality', async ({ page }) => {
  const calls = await mockApi(page, [
    { ...WARNING_DOC, state: 'approved' },
    { ...PRESELECTED_DOC, state: 'approved' },
  ]);
  await page.goto('/editorial');
  await expect(page.getByText('Vacancy rates in Berlin')).toBeVisible();

  await page.getByLabel('Select all').check();
  await expect(page.locator('.list-head select')).toHaveValue('mixed');
  await expect(page.locator('.list-head select')).toContainText('Mixed');

  await page.locator('.list-head select').selectOption('B');
  await page.getByRole('button', { name: 'Apply quality' }).click();
  await expect(
    page.getByRole('status').filter({ hasText: 'Source quality updated: 2 changed, 0 skipped.' }),
  ).toBeVisible();
  expect(calls.qualities).toHaveLength(1);
  expect(calls.qualities[0]).toContain('"source_quality":"B"');

  await page.locator('.list li select').first().selectOption('A');
  await expect(page.getByText('Source quality updated.', { exact: true })).toBeVisible();
  expect(calls.qualities.at(-1)).toContain('"source_quality":"A"');
});

test('an editor approves all selected documents with one source quality', async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto('/editorial');
  await expect(page.getByText('Vacancy rates in Berlin')).toBeVisible();
  await page.getByLabel('Select all').check();
  await page.getByRole('checkbox', { name: /I confirm the licence/ }).check();
  const batchQuality = page.locator('.approve-controls').getByLabel('Source quality');
  await batchQuality.selectOption('B');
  await page.getByRole('button', { name: /Approve selected/ }).click();
  await expect(page.getByRole('status').filter({ hasText: '2 documents approved.' })).toBeVisible();
  expect(calls.approvals).toHaveLength(2);
  expect(calls.approvals[0]).toContain('"source_quality":"B"');
});

test('the editorial queue has wide, dark and narrow captures', async ({ page }) => {
  await mockApi(page);
  await page.goto('/editorial');
  await expect(page.getByRole('heading', { name: 'Editorial queue' })).toBeVisible();
  await capture(page, 'editorial', '../docs/screenshots/phase-8');
});

// Live run: needs FS_E2E_EDITOR_EMAIL/PASSWORD/TOTP and a queued warning document.
// It approves that document and withdraws it again, so the corpus ends unchanged.
const editorEmail = process.env.FS_E2E_EDITOR_EMAIL ?? '';
const editorPassword = process.env.FS_E2E_EDITOR_PASSWORD ?? '';
const editorTotp = process.env.FS_E2E_EDITOR_TOTP ?? '';
const liveTitle = process.env.FS_E2E_EDITOR_DOC ?? '';

test('live: the editor approves and withdraws a queued document', async ({ page }) => {
  test.skip(!editorEmail || !editorPassword || !editorTotp || !liveTitle, 'editor E2E is not configured');
  await page.goto('/login');
  await page.getByLabel('Email').fill(editorEmail);
  await page.getByLabel('Password').fill(editorPassword);
  await page.getByLabel(/TOTP/).fill(totp(editorTotp));
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('heading', { name: 'Check a claim' })).toBeVisible();

  await page.goto('/editorial');
  await expect(page.getByRole('heading', { name: 'Editorial queue' })).toBeVisible();
  const entry = page.getByRole('button', { name: new RegExp(liveTitle) });
  await expect(entry).toBeVisible();
  await entry.click();
  await page.getByRole('checkbox', { name: /I confirm the licence/ }).check();
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Approved. Indexing started.' })).toBeVisible();

  // Wait until the worker has indexed the document, so withdrawal exercises the real
  // delete path rather than racing the indexer.
  await expect
    .poll(
      async () => {
        const response = await page.request.get('/v1/review/queue?state=indexed');
        const body = (await response.json()) as {
          data: { title: string; state: string }[];
        };
        return body.data.some((item) => item.title === liveTitle && item.state === 'indexed');
      },
      { timeout: 90_000 },
    )
    .toBe(true);

  await page.reload();
  await page.getByLabel('Show').selectOption('indexed');
  await page.getByRole('button', { name: new RegExp(liveTitle) }).click();
  await page.getByLabel('Reason').fill('E2E cleanup');
  await page.getByRole('button', { name: 'Withdraw' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Withdrawn. New citations stop.' })).toBeVisible();
});
