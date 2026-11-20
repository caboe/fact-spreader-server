import { expect, test } from '@playwright/test';

const SESSION = {
  user: {
    id: 'usr_researcher',
    email: 'researcher@test.invalid',
    display_name: 'Researcher',
    permissions: ['search:use'],
  },
  csrf_token: 'csrf-test',
  totp_setup_required: false,
};

const RESPONSE = {
  query: 'housing costs',
  mode: 'hybrid',
  top_k: 12,
  chunk_top_k: 7,
  documents: [
    {
      document: {
        id: 'doc_1',
        version: 1,
        title: 'Housing report',
        publisher: 'Test Institute',
        publication_date: '2026-01-02',
        source_quality: 'B',
        language: 'en',
        url: 'https://example.com/report',
        license: 'CC BY 4.0',
        redistribution: 'full_text',
      },
      chunks: [
        {
          chunk_id: 'chunk-1',
          reference_id: '1',
          content: 'Rent prices rose faster than incomes.',
          file_path: 'doc_1@v1',
          score: 0.91,
          order: 0,
        },
      ],
    },
  ],
  entities: [{ entity_name: 'Rent', file_path: 'doc_1@v1' }],
  relationships: [{ src_id: 'Rent', file_path: 'doc_1@v1' }],
  relevance: {
    floor: 0.4,
    margin: 0.15,
    top_score: 0.91,
    cut_chunks: 3,
    cut_entities: 4,
    cut_relationships: 5,
  },
  returned_chunks: 1,
  dropped_chunks: 2,
  returned_entities: 1,
  dropped_entities: 1,
  returned_relationships: 1,
  dropped_relationships: 0,
  took_ms: 12,
};

test('raw retrieval shows passages and graph data without a check', async ({ page }) => {
  let requestBody: unknown = null;
  await page.route('**/api/auth/session', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(SESSION),
    }),
  );
  await page.route('**/v1/retrieval', async (route) => {
    requestBody = JSON.parse(route.request().postData() ?? '{}');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(RESPONSE),
    });
  });

  await page.goto('/retrieval');

  await expect(page.getByRole('heading', { name: 'Raw retrieval' })).toBeVisible();
  await expect(page.getByRole('note')).toContainText('not a fact check');
  await expect(
    page.locator('header').getByRole('link', { name: 'Raw retrieval' }),
  ).toBeVisible();

  // A native select is intrinsically shorter than a text input; the form pins one
  // control height so the select, both number inputs and the button line up.
  const controls = [
    page.getByLabel('Retrieval mode'),
    page.getByLabel('Graph candidates'),
    page.getByLabel('Passages'),
    page.getByRole('button', { name: 'Retrieve' }),
  ];
  const heights = await Promise.all(
    controls.map(async (control) => (await control.boundingBox())?.height ?? 0),
  );
  expect(heights[0]).toBeGreaterThan(0);
  for (const height of heights) expect(height).toBeCloseTo(heights[0]!, 1);

  // The diagnostic default stays below the check pipeline's graph breadth: graph
  // candidates share LightRAG's context budget with the passages (DECISIONS.md D65).
  await expect(page.getByLabel('Graph candidates')).toHaveValue('10');
  await expect(page.getByLabel('Passages')).toHaveValue('20');

  await page.getByLabel('Query').fill('housing costs');
  await page.getByLabel('Retrieval mode').selectOption('hybrid');
  await page.getByLabel('Graph candidates').fill('12');
  await page.getByLabel('Passages').fill('7');
  await page.getByRole('button', { name: 'Retrieve' }).click();

  await expect(page.getByRole('heading', { name: 'Housing report' })).toBeVisible();
  await expect(page.locator('.chunk p').first()).toContainText(
    'Rent prices rose faster than incomes.',
  );
  await expect(page.getByText(/Documents: 1 · Passages: 1 · 12 ms/)).toBeVisible();
  await expect(page.getByText(/Filtered out: passages 2/)).toBeVisible();
  // The page shows the same relevance cut a check applies (DECISIONS.md D68).
  await expect(
    page.getByText(
      /Relevance cut \(same as a check\): floor 0\.40, within 0\.15 of the best match 0\.910\. Below the cut: passages 3 · entities 4 · relationships 5/,
    ),
  ).toBeVisible();
  await expect(page.getByText(/Source quality B/)).toBeVisible();

  await page.locator('details.graph summary').click();
  await expect(page.getByText(/Graph data: 1 entities, 1 relationships/)).toBeVisible();
  await page.locator('details.json summary').click();

  expect(requestBody).toEqual({
    query: 'housing costs',
    mode: 'hybrid',
    top_k: 12,
    chunk_top_k: 7,
    include_graph: true,
  });
});
