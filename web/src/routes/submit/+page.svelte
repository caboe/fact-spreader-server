<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import {
    ApiError,
    type BatchEstimateResponse,
    type BatchInfo,
    approveBatch,
    estimateBatch,
    getBatch,
    rejectBatch,
    retryBatch,
    submitBatch,
    type BatchActionResult,
    type SourceGrade,
  } from '$lib/api';
  import { session } from '$lib/session';
  import { t } from '$lib/i18n';

  const tr = $derived($t);
  const STORAGE_KEY = 'fs-batch';

  let files = $state<File[]>([]);
  let archive = $state<File | null>(null);
  let metadataFile = $state<File | null>(null);
  let urlsText = $state('');
  let publisher = $state('');
  let license = $state('');
  let language = $state('');
  let publicationDate = $state('');
  let domainTags = $state('');
  let estimate = $state<BatchEstimateResponse | null>(null);
  let estimateStale = $state(false);
  let acceptOverBudget = $state(false);
  let batch = $state<BatchInfo | null>(null);
  let selectedIds = $state<string[]>([]);
  let licenseConfirmed = $state(false);
  let redistribution = $state<'metadata_only' | 'excerpts_only' | 'full_text'>('metadata_only');
  let approvalQuality = $state<SourceGrade | ''>('');
  let rejectReason = $state('');
  let error = $state('');
  let notice = $state('');
  let busy = $state('');
  let dragging = $state(false);
  let timer: ReturnType<typeof setInterval> | null = null;

  const GRADES: SourceGrade[] = ['A', 'B', 'C', 'D'];
  const countKeys = ['total', 'ready', 'warning', 'duplicate', 'failed'] as const;
  const canSubmit = $derived(Boolean($session?.user.permissions.includes('documents:submit')));
  const canReview = $derived(Boolean($session?.user.permissions.includes('documents:review')));
  const selectable = $derived(
    (batch?.files ?? []).filter((file) => ['ready', 'warning', 'parsed'].includes(file.state)),
  );
  const selectedReady = $derived(
    selectable.filter((file) => selectedIds.includes(file.document_id)),
  );

  onMount(async () => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      try {
        await loadBatch(stored);
        startPolling();
      } catch {
        localStorage.removeItem(STORAGE_KEY);
      }
    }
  });

  onDestroy(() => stopPolling());

  function urls(): string[] {
    return urlsText
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);
  }

  function addFiles(incoming: FileList | File[]): void {
    const list = Array.from(incoming);
    const zip = list.find((file) => file.name.toLowerCase().endsWith('.zip'));
    if (zip) {
      archive = zip;
      files = [...files, ...list.filter((file) => file !== zip)];
    } else {
      files = [...files, ...list];
    }
    estimate = null;
    estimateStale = true;
    error = '';
  }

  function onDrop(event: DragEvent): void {
    event.preventDefault();
    dragging = false;
    if (event.dataTransfer?.files) addFiles(event.dataTransfer.files);
  }

  function removeFile(file: File): void {
    files = files.filter((item) => item !== file);
    estimate = null;
    estimateStale = true;
  }

  function changeFiles(event: Event): void {
    const input = event.currentTarget as HTMLInputElement;
    if (input.files) addFiles(input.files);
    input.value = '';
  }

  async function runEstimate(): Promise<void> {
    if (files.length === 0 && !archive && urls().length === 0) {
      error = tr('batch.no_files');
      return;
    }
    busy = 'estimate';
    error = '';
    notice = '';
    try {
      estimate = await estimateBatch({ files, archive: archive ?? undefined, urls: urls() });
      estimateStale = false;
      acceptOverBudget = false;
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function submit(): Promise<void> {
    if (estimate === null || estimateStale) {
      await runEstimate();
      if (estimate === null) return;
    }
    if (estimate.exceeds_budget && !acceptOverBudget) {
      error = tr('batch.accept_over_budget_hint');
      return;
    }
    busy = 'submit';
    error = '';
    notice = '';
    try {
      const result = await submitBatch({
        files,
        archive: archive ?? undefined,
        metadataFile: metadataFile ?? undefined,
        urls: urls(),
        metadata: {
          publisher: publisher || undefined,
          license: license || undefined,
          language: language || undefined,
          publication_date: publicationDate || undefined,
          domain_tags: domainTags
            ? domainTags.split(',').map((tag) => tag.trim()).filter(Boolean)
            : undefined,
        },
        acceptEstimate: acceptOverBudget,
      });
      batch = result.batch;
      localStorage.setItem(STORAGE_KEY, batch.id);
      files = [];
      archive = null;
      metadataFile = null;
      urlsText = '';
      estimate = null;
      notice = tr('batch.submitted');
      startPolling();
      await loadBatch(batch.id);
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function loadBatch(id: string): Promise<void> {
    try {
      batch = (await getBatch(id)).batch;
      selectedIds = selectedIds.filter((documentId) =>
        (batch?.files ?? []).some((file) => file.document_id === documentId),
      );
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) {
        localStorage.removeItem(STORAGE_KEY);
        batch = null;
      }
      throw cause;
    }
  }

  function startPolling(): void {
    stopPolling();
    timer = setInterval(async () => {
      if (!batch) return;
      try {
        await loadBatch(batch.id);
        if (batch.state !== 'processing') stopPolling();
      } catch {
        stopPolling();
      }
    }, 2500);
  }

  function stopPolling(): void {
    if (timer) clearInterval(timer);
    timer = null;
  }

  function toggle(id: string): void {
    selectedIds = selectedIds.includes(id)
      ? selectedIds.filter((item) => item !== id)
      : [...selectedIds, id];
  }

  function selectAll(): void {
    selectedIds = selectable.map((file) => file.document_id);
  }

  function resultProblems(results: BatchActionResult[]): string {
    const failed = results.filter((result) => result.error);
    if (failed.length === 0) return '';
    return failed
      .map((result) => `${result.document_id}: ${result.error}`)
      .join(', ');
  }

  async function approve(): Promise<void> {
    if (!batch || selectedIds.length === 0) return;
    if (!licenseConfirmed) {
      error = tr('editorial.license_required');
      return;
    }
    if (!approvalQuality) {
      error = tr('editorial.quality_required');
      return;
    }
    busy = 'approve';
    error = '';
    notice = '';
    try {
      const result = await approveBatch(batch.id, {
        document_ids: selectedIds,
        license_confirmed: true,
        redistribution,
        source_quality: approvalQuality,
      });
      const problems = resultProblems(result.results);
      if (problems) error = problems;
      else notice = tr('batch.approved_ok', { count: result.results.length });
      selectedIds = [];
      approvalQuality = '';
      await loadBatch(batch.id);
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function reject(): Promise<void> {
    if (!batch || selectedIds.length === 0 || !rejectReason.trim()) return;
    busy = 'reject';
    error = '';
    try {
      const result = await rejectBatch(batch.id, {
        document_ids: selectedIds,
        reason: rejectReason.trim(),
      });
      const problems = resultProblems(result.results);
      if (problems) error = problems;
      else notice = tr('batch.rejected_ok', { count: result.results.length });
      selectedIds = [];
      rejectReason = '';
      await loadBatch(batch.id);
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function retry(documentId: string): Promise<void> {
    if (!batch) return;
    busy = documentId;
    error = '';
    try {
      const result = await retryBatch(batch.id, [documentId]);
      const problems = resultProblems(result.results);
      if (problems) error = problems;
      else notice = tr('batch.retried_ok');
      await loadBatch(batch.id);
      startPolling();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  function reset(): void {
    localStorage.removeItem(STORAGE_KEY);
    stopPolling();
    batch = null;
    selectedIds = [];
    licenseConfirmed = false;
    notice = '';
    error = '';
  }

  function stateLabel(state: string): string {
    const key = `editorial.state_${state}`;
    const label = tr(key);
    return label === key ? state : label;
  }
</script>

<svelte:head><title>{tr('batch.title')} · Fact Spreader</title></svelte:head>

<h1>{tr('batch.title')}</h1>
<p class="intro">{tr('batch.intro')}</p>

{#if !canSubmit}
  <p class="notice" role="alert">{tr('batch.forbidden')}</p>
{:else if batch}
  <section class="panel">
    <header class="panel-head">
      <div>
        <h2>{tr('batch.batch')} {batch.id}</h2>
        <p class="meta">
          {stateLabel(batch.state)} · {tr('batch.estimated_cost')}: ${batch.estimated_usd.toFixed(4)}
          · {tr('batch.actual_cost')}: ${batch.actual_usd.toFixed(4)}
          {#if batch.budget_remaining_usd !== null && batch.budget_remaining_usd !== undefined}
            · {tr('batch.budget_remaining')}: ${batch.budget_remaining_usd.toFixed(2)}
          {/if}
        </p>
      </div>
      <button type="button" class="ghost" onclick={reset}>{tr('batch.new_batch')}</button>
    </header>

    <div class="counts">
      {#each countKeys as key}
        <div class="count-card">
          <span class="count-value">{batch.counts[key] ?? 0}</span>
          <span>{tr(`batch.count_${key}`)}</span>
        </div>
      {/each}
    </div>

    {#if (batch.warnings ?? []).length > 0}
      <ul class="warnings">
        {#each batch.warnings ?? [] as warning}
          <li>{warning.message}</li>
        {/each}
      </ul>
    {/if}

    <table>
      <thead>
        <tr>
          <th></th><th>{tr('batch.file')}</th><th>{tr('batch.state')}</th><th></th>
        </tr>
      </thead>
      <tbody>
        {#each batch.files ?? [] as file}
          <tr>
            <td>
              {#if canReview && ['ready', 'warning', 'parsed'].includes(file.state)}
                <input
                  type="checkbox"
                  checked={selectedIds.includes(file.document_id)}
                  aria-label={`${tr('editorial.select')} ${file.filename}`}
                  onchange={() => toggle(file.document_id)}
                />
              {/if}
            </td>
            <td>{file.filename}</td>
            <td><span class={`badge state-${file.state}`}>{stateLabel(file.state)}</span></td>
            <td class="right">
              {#if file.state === 'failed'}
                <button
                  type="button"
                  class="ghost"
                  onclick={() => retry(file.document_id)}
                  disabled={busy === file.document_id}>{tr('batch.retry')}</button
                >
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>

    {#if canReview && selectable.length > 0}
      <div class="review">
        <h3>{tr('batch.review')}</h3>
        <p class="meta">{tr('batch.review_hint')}</p>
        <div class="row">
          <button type="button" class="ghost" onclick={selectAll}>{tr('batch.select_all')}</button>
          <span>{selectedIds.length} {tr('batch.selected')}</span>
        </div>
        <label class="check">
          <input type="checkbox" bind:checked={licenseConfirmed} />
          <span>{tr('editorial.license_confirm')}</span>
        </label>
        <label class="field">
          <span>{tr('editorial.redistribution')}</span>
          <select bind:value={redistribution}>
            <option value="metadata_only">{tr('editorial.redistribution_metadata')}</option>
            <option value="excerpts_only">{tr('editorial.redistribution_excerpts')}</option>
            <option value="full_text">{tr('editorial.redistribution_full_text')}</option>
          </select>
        </label>
        <label class="field">
          <span>{tr('editorial.source_quality')}</span>
          <select bind:value={approvalQuality} required>
            <option value="">{tr('editorial.quality_choose')}</option>
            {#each GRADES as grade}<option value={grade}>{grade}</option>{/each}
          </select>
        </label>
        <div class="row">
          <button
            type="button"
            onclick={approve}
            disabled={selectedIds.length === 0 || !approvalQuality || busy === 'approve'}
            >{tr('editorial.approve')}</button
          >
          <label class="field">
            <span>{tr('editorial.reason')}</span>
            <input type="text" bind:value={rejectReason} />
          </label>
          <button
            type="button"
            class="danger"
            onclick={reject}
            disabled={selectedIds.length === 0 || !rejectReason.trim() || busy === 'reject'}
            >{tr('editorial.reject')}</button
          >
        </div>
      </div>
    {/if}
  </section>
{:else}
  <form class="panel" onsubmit={(event) => { event.preventDefault(); submit(); }}>
    <div
      class="drop"
      class:dragging
      role="button"
      tabindex="0"
      aria-label={tr('batch.drop')}
      ondragover={(event) => { event.preventDefault(); dragging = true; }}
      ondragleave={() => (dragging = false)}
      ondrop={onDrop}
      onkeydown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          document.getElementById('batch-files')?.click();
        }
      }}
    >
      <p>{tr('batch.drop')}</p>
      <p class="meta">{tr('batch.drop_hint')}</p>
      <input
        id="batch-files"
        type="file"
        multiple
        onchange={changeFiles}
        aria-label={tr('batch.choose_files')}
      />
      <input
        type="file"
        multiple
        webkitdirectory
        onchange={changeFiles}
        aria-label={tr('batch.choose_folder')}
      />
    </div>
    <p class="meta">{tr('batch.zip_hint')}</p>

    {#if files.length > 0 || archive}
      <ul class="picked">
        {#if archive}<li class="meta">{tr('batch.archive')}: {archive.name}</li>{/if}
        {#each files as file}
          <li>
            <span>{file.name} · {Math.ceil(file.size / 1024)} KB</span>
            <button type="button" class="link" onclick={() => removeFile(file)}>×</button>
          </li>
        {/each}
      </ul>
    {/if}

    <label class="field">
      <span>{tr('batch.urls')}</span>
      <textarea rows="3" bind:value={urlsText} placeholder="https://example.com/report"></textarea>
    </label>

    <h2>{tr('batch.metadata')}</h2>
    <div class="grid">
      <label class="field"><span>{tr('batch.publisher')}</span><input type="text" bind:value={publisher} /></label>
      <label class="field"><span>{tr('editorial.license')}</span><input type="text" bind:value={license} /></label>
      <label class="field"><span>{tr('batch.language')}</span><input type="text" bind:value={language} placeholder="en" /></label>
      <label class="field"><span>{tr('batch.publication_date')}</span><input type="date" bind:value={publicationDate} /></label>
      <label class="field"><span>{tr('batch.domain_tags')}</span><input type="text" bind:value={domainTags} placeholder="housing, berlin" /></label>
      <label class="field"><span>{tr('batch.sidecar')}</span><input type="file" accept=".csv,.json" onchange={(event) => { metadataFile = (event.currentTarget as HTMLInputElement).files?.[0] ?? null; }} /></label>
    </div>
    <p class="meta">{tr('batch.sidecar_hint')}</p>

    {#if estimate}
      <div class="estimate" role="status">
        <p>
          <strong>{tr('batch.estimate_ready')}</strong>
          ${estimate.estimate_usd.toFixed(4)} · {tr('batch.budget_remaining')}:
          ${estimate.budget_remaining_usd.toFixed(2)}
        </p>
        <p class="meta">
          {(estimate.files ?? []).length} {tr('batch.files')}
          {#if (estimate.warnings ?? []).length > 0} · {(estimate.warnings ?? []).map((warning) => warning.message).join('; ')}{/if}
        </p>
        {#if estimate.exceeds_budget}
          <p class="error" role="alert">{tr('batch.estimate_exceeds')}</p>
          <label class="check">
            <input type="checkbox" bind:checked={acceptOverBudget} />
            <span>{tr('batch.accept_over_budget')}</span>
          </label>
        {/if}
      </div>
    {/if}

    <div class="row">
      <button type="button" class="ghost" onclick={runEstimate} disabled={busy === 'estimate'}>
        {tr('batch.estimate')}
      </button>
      <button
        type="submit"
        disabled={busy === 'submit' || (estimate !== null && estimate.exceeds_budget && !acceptOverBudget)}
        >{tr('batch.submit')}</button
      >
    </div>
    <p class="meta">{tr('batch.submit_hint')}</p>
  </form>
{/if}

{#if error}<p class="error" role="alert">{error}</p>{/if}
{#if notice}<p class="ok" role="status">{notice}</p>{/if}

<style>
  .intro {
    max-width: 60rem;
    color: var(--fs-muted);
  }
  .panel {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1.2rem;
    display: grid;
    gap: 0.9rem;
    max-width: 64rem;
  }
  .panel-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 1rem;
  }
  .panel h2 {
    margin: 0;
  }
  .panel-head h2 {
    font-size: 1.1rem;
  }
  .drop {
    border: 2px dashed var(--fs-border);
    border-radius: var(--fs-radius);
    padding: 1.3rem;
    text-align: center;
    display: grid;
    gap: 0.5rem;
    cursor: pointer;
  }
  .drop.dragging {
    border-color: var(--fs-accent);
    background: var(--fs-accent-soft);
  }
  .drop input {
    margin: 0.2rem auto;
  }
  .picked {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    gap: 0.3rem;
  }
  .picked li {
    display: flex;
    justify-content: space-between;
    gap: 0.5rem;
    font-size: 0.9rem;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
    gap: 0.7rem;
  }
  .field {
    display: grid;
    gap: 0.25rem;
    font-size: 0.9rem;
  }
  .field span {
    color: var(--fs-muted);
  }
  .field input,
  .field textarea,
  .field select,
  .review select {
    padding: 0.5rem;
    font: inherit;
    border-radius: 0.4rem;
    border: 1px solid var(--fs-border);
    background: var(--fs-bg);
    color: var(--fs-text);
  }
  .counts {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(7rem, 1fr));
    gap: 0.5rem;
  }
  .count-card {
    background: var(--fs-bg);
    border-radius: 0.6rem;
    padding: 0.6rem 0.8rem;
    display: grid;
    gap: 0.1rem;
    font-size: 0.8rem;
    color: var(--fs-muted);
  }
  .count-value {
    font-size: 1.25rem;
    font-weight: 700;
    color: var(--fs-text);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
  }
  th {
    text-align: left;
    color: var(--fs-muted);
    font-weight: 600;
    padding: 0.4rem 0.3rem;
  }
  td {
    padding: 0.4rem 0.3rem;
  }
  .right {
    text-align: right;
  }
  .badge {
    display: inline-block;
    padding: 0.1rem 0.45rem;
    border-radius: 999px;
    background: var(--fs-bg);
    font-size: 0.78rem;
  }
  .badge.state-warning {
    color: var(--fs-false);
  }
  .badge.state-ready,
  .badge.state-parsed {
    color: var(--fs-accent);
  }
  .badge.state-failed {
    color: var(--fs-false);
  }
  .review {
    display: grid;
    gap: 0.6rem;
    margin-top: 0.6rem;
  }
  .row {
    display: flex;
    gap: 0.6rem;
    align-items: flex-end;
    flex-wrap: wrap;
  }
  .row .field {
    flex: 1;
  }
  .check {
    display: flex;
    gap: 0.4rem;
    align-items: center;
    font-size: 0.88rem;
  }
  .estimate {
    background: var(--fs-bg);
    border-radius: 0.6rem;
    padding: 0.7rem 0.9rem;
    display: grid;
    gap: 0.3rem;
  }
  .estimate p {
    margin: 0;
  }
  .warnings {
    margin: 0;
    padding-left: 1.1rem;
    color: var(--fs-false);
    font-size: 0.88rem;
  }
  button {
    font: inherit;
  }
  button:not(.link) {
    padding: 0.5rem 1rem;
    border-radius: 0.5rem;
    border: none;
    background: var(--fs-accent);
    color: var(--fs-accent-contrast);
    font-weight: 600;
    cursor: pointer;
  }
  button.ghost {
    background: var(--fs-accent-soft);
    color: var(--fs-accent);
  }
  button.danger {
    background: var(--fs-false);
    color: #fff;
  }
  button.link {
    background: none;
    border: none;
    color: var(--fs-muted);
    font-size: 1.1rem;
    cursor: pointer;
  }
  button:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
  .meta {
    color: var(--fs-muted);
    font-size: 0.85rem;
    margin: 0;
  }
  .error {
    color: var(--fs-false);
  }
  .ok {
    color: var(--fs-true);
  }
  .notice {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1rem;
  }
</style>
