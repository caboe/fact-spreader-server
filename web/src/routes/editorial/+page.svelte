<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import {
    ApiError,
    type DocumentInfo,
    type EditorContradiction,
    type EditorGap,
    approveDocument,
    bulkUpdateDocumentQuality,
    getDocument,
    getDocumentContent,
    getIndexingStatus,
    listContradictions,
    listGaps,
    listReviewQueue,
    rejectDocument,
    recheckGap,
    restartDocumentIndex,
    updateContradiction,
    updateDocumentQuality,
    updateFigure,
    updateGap,
    withdrawDocument,
    type IndexingStatusItem,
    type IndexingStatusResponse,
    type SourceGrade,
  } from '$lib/api';
  import { session } from '$lib/session';
  import { t } from '$lib/i18n';

  const tr = $derived($t);
  type Tab = 'queue' | 'contradictions' | 'gaps';

  let tab = $state<Tab>('queue');
  let queue = $state<DocumentInfo[]>([]);
  let indexingStatus = $state<IndexingStatusResponse>({ active: [], aborted: [] });
  let counts = $state<Record<string, number>>({});
  let progressTimer: ReturnType<typeof setInterval> | null = null;
  let filters = $state({ state: '', q: '', source_quality: '', publisher: '', language: '' });
  let selectedIds = $state<string[]>([]);
  let detail = $state<DocumentInfo | null>(null);
  let content = $state('');
  let figureDraft = $state<Record<string, string>>({});
  let contradictions = $state<EditorContradiction[]>([]);
  let gaps = $state<EditorGap[]>([]);
  let error = $state('');
  let notice = $state('');
  let busy = $state('');

  let licenseConfirmed = $state(false);
  let redistribution = $state<'metadata_only' | 'excerpts_only' | 'full_text'>('metadata_only');
  let approvalQuality = $state<SourceGrade | ''>('');
  let batchQuality = $state<SourceGrade | ''>('');
  let headerQuality = $state<SourceGrade | 'mixed' | ''>('');
  let note = $state('');
  let rejectReason = $state('');
  let withdrawReason = $state('');

  const GRADES: SourceGrade[] = ['A', 'B', 'C', 'D'];
  const COUNT_FILTERS: Record<string, string> = {
    ready: 'ready',
    warnings: 'warning',
    duplicates: 'duplicate',
    approved: 'approved',
    indexed: 'indexed',
  };
  const canReview = $derived(
    Boolean($session?.user.permissions.includes('documents:review')),
  );
  const allVisibleSelected = $derived(
    queue.length > 0 && queue.every((document) => selectedIds.includes(document.id)),
  );
  const selectedDocuments = $derived(queue.filter((document) => selectedIds.includes(document.id)));
  const qualityEligible = $derived(
    selectedDocuments.length > 0 &&
      selectedDocuments.every((document) =>
        ['approved', 'indexing', 'indexed'].includes(document.state),
      ),
  );
  const canApplyQuality = $derived(
    qualityEligible && ['A', 'B', 'C', 'D'].includes(headerQuality),
  );
  const approvableSelected = $derived(
    selectedDocuments.length > 0 &&
      selectedDocuments.every((document) =>
        ['ready', 'warning', 'parsed'].includes(document.state),
      ),
  );
  const activeIndexing = $derived(indexingStatus.active ?? []);
  const abortedIndexing = $derived(indexingStatus.aborted ?? []);
  const approvedCohort = $derived(
    (counts.approved ?? 0) + (counts.indexing ?? 0) + (counts.indexed ?? 0),
  );
  const indexingPending = $derived(
    (counts.approved ?? 0) + (counts.indexing ?? 0),
  );
  const progressPercent = $derived(
    approvedCohort > 0
      ? Math.round(((counts.indexed ?? 0) / approvedCohort) * 100)
      : 0,
  );
  const failedCount = $derived(counts.failed ?? 0);

  onMount(async () => {
    await Promise.all([loadQueue(), loadContradictions(), loadGaps()]);
    await loadIndexing();
    progressTimer = setInterval(() => {
      if ((counts.approved ?? 0) + (counts.indexing ?? 0) > 0) void loadProgress();
    }, 5000);
  });

  onDestroy(() => {
    if (progressTimer) clearInterval(progressTimer);
  });

  async function loadIndexing(): Promise<void> {
    try {
      indexingStatus = await getIndexingStatus();
    } catch {
      /* keep the last visible progress */
    }
  }

  async function loadProgress(): Promise<void> {
    try {
      const snapshot = await listReviewQueue({ state: 'all', limit: 1 });
      counts = snapshot.counts;
    } catch {
      /* keep the last visible progress */
    }
    await loadIndexing();
  }

  async function openIndexDocument(item: IndexingStatusItem): Promise<void> {
    try {
      await selectDocument(await getDocument(item.document_id));
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    }
  }

  function indexJobReason(item: IndexingStatusItem): string {
    if (!item.job_id) return tr('editorial.aborted_no_job');
    if (item.stale) return tr('editorial.aborted_stale');
    if (item.job_state === 'failed') return tr('editorial.aborted_failed');
    return stateLabel(item.job_state ?? 'failed');
  }

  function indexJobError(item: IndexingStatusItem): string {
    const message = item.error?.message;
    return typeof message === 'string' ? message : '';
  }

  async function restartIndex(item: IndexingStatusItem): Promise<void> {
    busy = `restart:${item.document_id}`;
    error = '';
    notice = '';
    try {
      const updated = await restartDocumentIndex(item.document_id);
      if (detail?.id === updated.id) detail = updated;
      notice = tr('editorial.restart_ok');
      await loadQueue();
      await loadProgress();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function applyCountFilter(key: string): Promise<void> {
    const state = COUNT_FILTERS[key];
    if (!state) return;
    filters.state = state;
    await loadQueue();
  }

  async function loadQueue(): Promise<void> {
    error = '';
    try {
      const result = await listReviewQueue({ ...filters, limit: 200 });
      queue = result.data;
      counts = result.counts;
      selectedIds = [];
      syncHeaderQuality();
      if (!detail && queue.length > 0) await selectDocument(queue[0]!);
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    }
  }

  async function loadContradictions(): Promise<void> {
    try {
      contradictions = (await listContradictions()).data;
    } catch {
      contradictions = [];
    }
  }

  async function loadGaps(): Promise<void> {
    try {
      gaps = (await listGaps({ sort: 'frequency' })).data;
    } catch {
      gaps = [];
    }
  }

  async function selectDocument(document: DocumentInfo): Promise<void> {
    detail = document;
    content = '';
    figureDraft = Object.fromEntries(
      (document.figures ?? []).map((figure) => [figure.id, figure.description ?? '']),
    );
    licenseConfirmed = false;
    approvalQuality = '';
    note = '';
    rejectReason = '';
    withdrawReason = '';
    try {
      const [fresh, text] = await Promise.all([
        getDocument(document.id),
        getDocumentContent(document.id),
      ]);
      detail = fresh;
      content = text;
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    }
  }

  async function refreshSelected(): Promise<void> {
    if (!detail) return;
    const fresh = await getDocument(detail.id);
    detail = fresh;
    if (!queue.some((item) => item.id === fresh.id)) return;
    queue = queue.map((item) => (item.id === fresh.id ? fresh : item));
  }

  function syncHeaderQuality(): void {
    const values = new Set(selectedDocuments.map((document) => document.source_quality));
    headerQuality =
      selectedDocuments.length === 0
        ? ''
        : values.size === 1
          ? ([...values][0] as SourceGrade)
          : 'mixed';
  }

  function toggle(document: DocumentInfo): void {
    selectedIds = selectedIds.includes(document.id)
      ? selectedIds.filter((id) => id !== document.id)
      : [...selectedIds, document.id];
    syncHeaderQuality();
  }

  function toggleAll(event: Event): void {
    const checked = (event.currentTarget as HTMLInputElement).checked;
    selectedIds = checked ? queue.map((document) => document.id) : [];
    syncHeaderQuality();
  }

  async function approveOne(id: string, quality: SourceGrade): Promise<void> {
    await approveDocument(id, {
      license_confirmed: true,
      redistribution,
      source_quality: quality,
      note: note || undefined,
    });
  }

  async function approve(): Promise<void> {
    if (!detail) return;
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
      detail = await approveDocument(detail.id, {
        license_confirmed: true,
        redistribution,
        source_quality: approvalQuality,
        note: note || undefined,
      });
      notice = tr('editorial.approved_ok');
      approvalQuality = '';
      await loadQueue();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function approveSelected(): Promise<void> {
    if (!licenseConfirmed) {
      error = tr('editorial.license_required');
      return;
    }
    if (!batchQuality) {
      error = tr('editorial.quality_required');
      return;
    }
    busy = 'batch';
    error = '';
    notice = '';
    try {
      let approved = 0;
      for (const id of selectedIds) {
        try {
          await approveOne(id, batchQuality);
          approved += 1;
        } catch (cause) {
          error = cause instanceof ApiError ? cause.message : tr('common.error');
        }
      }
      selectedIds = [];
      batchQuality = '';
      syncHeaderQuality();
      notice = tr('editorial.approved_count', { count: approved });
      await loadQueue();
    } finally {
      busy = '';
    }
  }

  async function applyHeaderQuality(): Promise<void> {
    if (!canApplyQuality || headerQuality === '' || headerQuality === 'mixed') return;
    const quality = headerQuality;
    busy = 'quality-bulk';
    error = '';
    notice = '';
    try {
      const result = await bulkUpdateDocumentQuality({
        document_ids: selectedIds,
        source_quality: quality,
        note: 'Editorial quality change',
      });
      const updated = result.results.filter((item) => !item.error).length;
      const skipped = result.results.filter((item) => item.error).length;
      notice = tr('editorial.quality_updated', { count: updated, skipped });
      selectedIds = [];
      syncHeaderQuality();
      await loadQueue();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function saveRowQuality(document: DocumentInfo, grade: SourceGrade): Promise<void> {
    busy = document.id;
    error = '';
    notice = '';
    try {
      const updated = await updateDocumentQuality(document.id, {
        source_quality: grade,
        note: 'Editorial quality change',
      });
      queue = queue.map((item) => (item.id === updated.id ? updated : item));
      if (detail?.id === updated.id) detail = updated;
      syncHeaderQuality();
      notice = tr('editorial.quality_saved');
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
      await loadQueue();
    } finally {
      busy = '';
    }
  }

  async function reject(): Promise<void> {
    if (!detail || !rejectReason.trim()) return;
    busy = 'reject';
    error = '';
    try {
      detail = await rejectDocument(detail.id, rejectReason.trim());
      notice = tr('editorial.rejected_ok');
      await loadQueue();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function withdraw(): Promise<void> {
    if (!detail || !withdrawReason.trim()) return;
    busy = 'withdraw';
    error = '';
    try {
      detail = await withdrawDocument(detail.id, withdrawReason.trim());
      notice = tr('editorial.withdrawn_ok');
      await loadQueue();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function saveFigure(figureId: string): Promise<void> {
    if (!detail) return;
    busy = figureId;
    error = '';
    try {
      detail = await updateFigure(detail.id, figureId, figureDraft[figureId] ?? '');
      notice = tr('editorial.figure_saved');
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function setContradictionState(
    entry: EditorContradiction,
    state: string,
  ): Promise<void> {
    busy = entry.id;
    try {
      await updateContradiction(entry.id, state);
      await loadContradictions();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function setGapState(entry: EditorGap, state: string): Promise<void> {
    busy = entry.id;
    try {
      await updateGap(entry.id, state);
      await loadGaps();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function recheck(entry: EditorGap): Promise<void> {
    busy = entry.id;
    try {
      const result = await recheckGap(entry.id, 5);
      notice = tr('editorial.recheck_sent', {
        count: result.jobs.length,
        skipped: result.skipped_budget,
      });
      await loadGaps();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  function stateLabel(state: string): string {
    const key = `editorial.state_${state}`;
    const label = tr(key);
    return label === key ? state : label;
  }
</script>

<svelte:head><title>{tr('editorial.title')} · Fact Spreader</title></svelte:head>

<h1>{tr('editorial.title')}</h1>
<p class="intro">{tr('editorial.intro')}</p>

{#if !canReview}
  <p class="notice" role="alert">{tr('editorial.forbidden')}</p>
{:else}
  <div class="tabs" role="tablist" aria-label={tr('editorial.title')}>
    <button type="button" role="tab" aria-selected={tab === 'queue'} onclick={() => (tab = 'queue')}
      >{tr('editorial.tab_queue')}</button
    >
    <button
      type="button"
      role="tab"
      aria-selected={tab === 'contradictions'}
      onclick={() => (tab = 'contradictions')}
      >{tr('editorial.tab_contradictions')} <span class="count">{contradictions.length}</span></button
    >
    <button
      type="button"
      role="tab"
      aria-selected={tab === 'gaps'}
      onclick={() => (tab = 'gaps')}
      >{tr('editorial.tab_gaps')} <span class="count">{gaps.length}</span></button
    >
  </div>

  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if notice}<p class="ok" role="status">{notice}</p>{/if}

  {#if tab === 'queue'}
    <section class="counts" aria-label={tr('editorial.counts')}>
      {#each ['ready', 'warnings', 'duplicates', 'approved', 'indexed'] as key}
        <button
          type="button"
          class="count-card"
          aria-pressed={filters.state === COUNT_FILTERS[key]}
          onclick={() => applyCountFilter(key)}
        >
          <span class="count-value">{counts[key] ?? 0}</span>
          <span>{tr(`editorial.count_${key}`)}</span>
        </button>
      {/each}
    </section>

    {#if approvedCohort > 0}
      <section class="index-progress" aria-label={tr('editorial.progress_title')}>
        <div class="progress-head">
          <span>{tr('editorial.progress_title')}</span>
          <strong>{progressPercent}%</strong>
        </div>
        <progress
          value={counts.indexed ?? 0}
          max={approvedCohort}
          aria-label={tr('editorial.progress_title')}
        ></progress>
        {#if indexingPending > 0}
          <p class="progress-summary">
            {tr('editorial.progress_summary', {
              indexed: counts.indexed ?? 0,
              total: approvedCohort,
              running: activeIndexing.length,
              waiting: counts.approved ?? 0,
            })}
          </p>
        {:else}
          <p class="progress-summary">
            {tr('editorial.progress_complete', { total: approvedCohort })}
          </p>
        {/if}
        {#if activeIndexing.length > 0}
          <div class="indexing-now">
            <span class="muted small">{tr('editorial.indexing_now')}</span>
            <ul class="indexing-list">
              {#each activeIndexing as item}
                <li>
                  <button type="button" class="link-button" onclick={() => openIndexDocument(item)}
                    >{item.title}</button
                  >
                </li>
              {/each}
            </ul>
          </div>
        {/if}
        {#if abortedIndexing.length > 0}
          <div class="aborted">
            <span class="muted small"
              >{tr('editorial.aborted_title')} ({abortedIndexing.length})</span
            >
            <ul class="indexing-list">
              {#each abortedIndexing as item}
                <li class="aborted-item">
                  <div class="aborted-copy">
                    <button type="button" class="link-button" onclick={() => openIndexDocument(item)}
                      >{item.title}</button
                    >
                    <span class="muted small"
                      >{indexJobReason(item)}{#if item.job_id}
                        · {tr('editorial.index_attempts', { count: item.attempts })}{/if}</span
                    >
                    {#if indexJobError(item)}
                      <span class="warn small">{indexJobError(item)}</span>
                    {/if}
                  </div>
                  <button
                    type="button"
                    class="ghost restart-button"
                    disabled={busy === `restart:${item.document_id}`}
                    onclick={() => restartIndex(item)}
                    >{busy === `restart:${item.document_id}`
                      ? tr('editorial.restarting')
                      : tr('editorial.restart_index')}</button
                  >
                </li>
              {/each}
            </ul>
          </div>
        {/if}
        {#if failedCount > 0}
          <p class="warn small">
            {tr('editorial.progress_failed', { count: failedCount })}
            <button
              type="button"
              class="link-button"
              onclick={() => {
                filters.state = 'failed';
                loadQueue();
              }}>{tr('editorial.progress_show_failed')}</button
            >
          </p>
        {/if}
      </section>
    {/if}

    <form
      class="filters"
      onsubmit={(event) => {
        event.preventDefault();
        loadQueue();
      }}
    >
      <label class="search">
        <span>{tr('editorial.search')}</span>
        <input type="search" bind:value={filters.q} placeholder={tr('editorial.search_placeholder')} />
      </label>
      <label>
        <span>{tr('editorial.filter')}</span>
        <select bind:value={filters.state} onchange={loadQueue}>
          <option value="">{tr('editorial.filter_pending')}</option>
          <option value="all">{tr('editorial.filter_all')}</option>
          <option value="ready">{tr('editorial.filter_ready')}</option>
          <option value="warning">{tr('editorial.filter_warnings')}</option>
          <option value="duplicate">{tr('editorial.filter_duplicates')}</option>
          <option value="approved">{tr('editorial.filter_approved')}</option>
          <option value="indexing">{tr('editorial.filter_indexing')}</option>
          <option value="indexed">{tr('editorial.filter_indexed')}</option>
          <option value="failed">{tr('editorial.filter_failed')}</option>
          <option value="rejected">{tr('editorial.filter_rejected')}</option>
          <option value="withdrawn">{tr('editorial.filter_withdrawn')}</option>
        </select>
      </label>
      <label>
        <span>{tr('editorial.source_quality')}</span>
        <select bind:value={filters.source_quality} onchange={loadQueue}>
          <option value="">{tr('editorial.filter_any')}</option>
          {#each GRADES as grade}<option value={grade}>{grade}</option>{/each}
        </select>
      </label>
      <label>
        <span>{tr('editorial.publisher')}</span>
        <input type="text" bind:value={filters.publisher} />
      </label>
      <label>
        <span>{tr('editorial.language')}</span>
        <select bind:value={filters.language} onchange={loadQueue}>
          <option value="">{tr('editorial.filter_any')}</option>
          {#each ['en', 'de', 'fr', 'es'] as code}<option value={code}>{code}</option>{/each}
        </select>
      </label>
      <button type="submit" class="ghost">{tr('editorial.search')}</button>
    </form>

    <div class="split">
      <section class="list" aria-label={tr('editorial.queue')}>
        <div class="list-head">
          <label class="select-all">
            <input type="checkbox" checked={allVisibleSelected} onchange={toggleAll} />
            <span>{tr('editorial.select_all')}</span>
          </label>
          <span class="selected-count">{selectedIds.length} {tr('editorial.selected')}</span>
          <div class="bulk-quality">
            <label>
              <span>{tr('editorial.source_quality')}</span>
              <select bind:value={headerQuality} disabled={selectedIds.length === 0}>
                <option value="">—</option>
                {#if headerQuality === 'mixed'}
                  <option value="mixed" disabled>{tr('editorial.quality_mixed')}</option>
                {/if}
                {#each GRADES as grade}<option value={grade}>{grade}</option>{/each}
              </select>
            </label>
            <button
              type="button"
              class="ghost"
              onclick={applyHeaderQuality}
              disabled={!canApplyQuality || busy === 'quality-bulk'}
              >{tr('editorial.quality_apply')}</button
            >
          </div>
        </div>
        {#if selectedIds.length > 0 && !qualityEligible}
          <p class="muted small">{tr('editorial.quality_only_approved')}</p>
        {/if}
        <div class="approve-controls">
          <label class="confirm">
            <input type="checkbox" bind:checked={licenseConfirmed} />
            <span>{tr('editorial.license_confirm')}</span>
          </label>
          <label class="redistribution">
            <span>{tr('editorial.redistribution')}</span>
            <select bind:value={redistribution}>
              <option value="metadata_only">{tr('editorial.redistribution_metadata')}</option>
              <option value="excerpts_only">{tr('editorial.redistribution_excerpts')}</option>
              <option value="full_text">{tr('editorial.redistribution_full_text')}</option>
            </select>
          </label>
          <label class="approval-quality">
            <span>{tr('editorial.source_quality')}</span>
            <select bind:value={batchQuality}>
              <option value="">{tr('editorial.quality_choose')}</option>
              {#each GRADES as grade}<option value={grade}>{grade}</option>{/each}
            </select>
          </label>
          <button
            type="button"
            onclick={approveSelected}
            disabled={!approvableSelected || !batchQuality || busy === 'batch'}
            >{tr('editorial.approve_selected')} ({selectedIds.length})</button
          >
        </div>
        {#if queue.length === 0}
          <p class="muted">{tr('editorial.empty')}</p>
        {/if}
        <ul>
          {#each queue as document}
            <li class:active={detail?.id === document.id}>
              <input
                type="checkbox"
                checked={selectedIds.includes(document.id)}
                aria-label={`${tr('editorial.select')} ${document.title}`}
                onchange={() => toggle(document)}
              />
              <button type="button" class="entry" onclick={() => selectDocument(document)}>
                <span class="title">{document.title}</span>
                <span class="meta"
                  >{document.publisher} · {stateLabel(document.state)}
                  {#if (document.warnings?.length ?? 0) > 0}
                    · <span class="warn">{document.warnings?.length} {tr('editorial.warnings')}</span>
                  {/if}
                  {#if document.approval_preselected}
                    · <span class="preselect">{tr('editorial.preselected')}</span>
                  {/if}
                </span>
              </button>
              {#if ['approved', 'indexing', 'indexed'].includes(document.state)}
                <select
                  class="row-quality"
                  value={document.source_quality}
                  aria-label={`${tr('editorial.source_quality')} ${document.title}`}
                  disabled={busy === document.id}
                  onchange={(event) => saveRowQuality(document, event.currentTarget.value as SourceGrade)}
                >
                  {#each GRADES as grade}<option value={grade}>{grade}</option>{/each}
                </select>
              {:else}
                <span class="quality-readonly" title={tr('editorial.quality_at_approval')}
                  >{document.source_quality}</span
                >
              {/if}
            </li>
          {/each}
        </ul>
      </section>

      <section class="detail" aria-label={tr('editorial.detail')}>
        {#if !detail}
          <p class="muted">{tr('editorial.select_hint')}</p>
        {:else}
          <header>
            <h2>{detail.title}</h2>
            <p class="meta">
              {detail.publisher} · {stateLabel(detail.state)} · {tr('editorial.version')} {detail.version}
            </p>
          </header>

          <dl>
            <dt>{tr('editorial.language')}</dt><dd>{detail.language}</dd>
            <dt>{tr('editorial.license')}</dt><dd>{detail.license ?? '—'}</dd>
            <dt>{tr('editorial.source_quality')}</dt><dd>{detail.source_quality}</dd>
            <dt>{tr('editorial.submitted_by')}</dt><dd>{detail.submitted_by ?? '—'}</dd>
            <dt>{tr('editorial.state')}</dt><dd>{stateLabel(detail.state)}</dd>
          </dl>

          {#if (detail.warnings?.length ?? 0) > 0}
            <div class="warnings" role="status">
              <h3>{tr('editorial.warnings')}</h3>
              <ul>
                {#each detail.warnings ?? [] as warning}
                  <li><strong>{warning.code}</strong> {warning.message}</li>
                {/each}
              </ul>
            </div>
          {/if}

          {#if (detail.figures?.length ?? 0) > 0}
            <div class="figures">
              <h3>{tr('editorial.figures')}</h3>
              {#each detail.figures ?? [] as figure}
                <div class="figure">
                  <p class="meta">
                    {tr('editorial.figure')} {figure.number ?? figure.id}
                    {#if figure.editor_checked}
                      · <span class="preselect">{tr('editorial.figure_checked')}</span>
                    {/if}
                  </p>
                  {#if figure.caption}<p>{figure.caption}</p>{/if}
                  <label>
                    <span>{tr('editorial.figure_description')}</span>
                    <textarea rows="3" bind:value={figureDraft[figure.id]}></textarea>
                  </label>
                  <button
                    type="button"
                    class="ghost"
                    onclick={() => saveFigure(figure.id)}
                    disabled={busy === figure.id}
                    >{tr('editorial.save_figure')}</button
                  >
                </div>
              {/each}
            </div>
          {/if}

          <div class="content-block">
            <h3>{tr('editorial.content')}</h3>
            <pre>{content || '…'}</pre>
          </div>

          {#if ['ready', 'warning', 'parsed'].includes(detail.state)}
            <div class="actions">
              <label>
                <span>{tr('editorial.source_quality')}</span>
                <select bind:value={approvalQuality} required>
                  <option value="">{tr('editorial.quality_choose')}</option>
                  {#each GRADES as grade}<option value={grade}>{grade}</option>{/each}
                </select>
              </label>
              <label>
                <span>{tr('editorial.note')}</span>
                <input type="text" bind:value={note} />
              </label>
              <button
                type="button"
                onclick={approve}
                disabled={busy === 'approve' || !licenseConfirmed || !approvalQuality}
              >
                {tr('editorial.approve')}
              </button>
            </div>
            <div class="actions">
              <label>
                <span>{tr('editorial.reason')}</span>
                <input type="text" bind:value={rejectReason} />
              </label>
              <button
                type="button"
                class="danger"
                onclick={reject}
                disabled={busy === 'reject' || !rejectReason.trim()}>{tr('editorial.reject')}</button
              >
            </div>
          {:else if ['approved', 'indexing', 'indexed'].includes(detail.state)}
            <div class="actions">
              <label>
                <span>{tr('editorial.reason')}</span>
                <input type="text" bind:value={withdrawReason} />
              </label>
              <button
                type="button"
                class="danger"
                onclick={withdraw}
                disabled={busy === 'withdraw' || !withdrawReason.trim()}
                >{tr('editorial.withdraw')}</button
              >
            </div>
          {/if}
        {/if}
      </section>
    </div>
  {:else if tab === 'contradictions'}
    <p class="muted">{tr('editorial.contradictions_hint')}</p>
    {#if contradictions.length === 0}<p class="muted">{tr('editorial.contradictions_empty')}</p>{/if}
    <ul class="records">
      {#each contradictions as entry}
        <li>
          <p class="statement">{entry.statement_text}</p>
          <p class="meta">
            {stateLabel(entry.state)} · {entry.detected_at} · {tr('editorial.supporting')}:
            {entry.supporting.length} · {tr('editorial.refuting')}: {entry.refuting.length}
          </p>
          {#if entry.result_ids.length > 0}
            <p class="meta">{tr('editorial.results')}: {entry.result_ids.join(', ')}</p>
          {/if}
          {#if entry.state === 'open'}
            <div class="buttons">
              <button type="button" class="ghost" onclick={() => setContradictionState(entry, 'acknowledged')}
                >{tr('editorial.acknowledge')}</button
              >
              <button type="button" class="ghost" onclick={() => setContradictionState(entry, 'resolved')}
                >{tr('editorial.resolve')}</button
              >
            </div>
          {/if}
        </li>
      {/each}
    </ul>
  {:else}
    <p class="muted">{tr('editorial.gaps_hint')}</p>
    {#if gaps.length === 0}<p class="muted">{tr('editorial.gaps_empty')}</p>{/if}
    <ul class="records">
      {#each gaps as entry}
        <li>
          <p class="statement">{entry.query}</p>
          <p class="meta">
            {stateLabel(entry.state)} · {entry.language} · {tr('editorial.frequency')}: {entry.frequency}
            · {tr('editorial.last_seen')}: {entry.last_seen}
          </p>
          <p class="meta">{tr('editorial.topics')}: {entry.topics.join(', ') || '—'}</p>
          {#if entry.state === 'open'}
            <div class="buttons">
              <button type="button" class="ghost" onclick={() => recheck(entry)} disabled={busy === entry.id}
                >{tr('editorial.recheck')}</button
              >
              <button type="button" class="ghost" onclick={() => setGapState(entry, 'linked')}
                >{tr('editorial.link')}</button
              >
              <button type="button" class="ghost" onclick={() => setGapState(entry, 'dismissed')}
                >{tr('editorial.dismiss')}</button
              >
            </div>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
{/if}

<style>
  .intro {
    max-width: 60rem;
    color: var(--fs-muted);
  }
  .tabs {
    display: flex;
    gap: 0.4rem;
    margin: 1.2rem 0;
    flex-wrap: wrap;
  }
  .tabs button {
    padding: 0.45rem 0.9rem;
    border-radius: 999px;
    border: none;
    background: var(--fs-surface);
    color: var(--fs-text);
    box-shadow: var(--fs-shadow-soft);
    font: inherit;
    cursor: pointer;
  }
  .tabs button[aria-selected='true'] {
    background: var(--fs-accent-soft);
    color: var(--fs-accent);
    font-weight: 700;
  }
  .count {
    font-size: 0.8rem;
    opacity: 0.8;
  }
  .counts {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr));
    gap: 0.6rem;
    margin-bottom: 1rem;
  }
  .count-card {
    appearance: none;
    border: none;
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 0.7rem 0.9rem;
    display: grid;
    gap: 0.15rem;
    font: inherit;
    font-size: 0.85rem;
    color: var(--fs-muted);
    text-align: left;
    cursor: pointer;
  }
  .count-card:hover {
    box-shadow: var(--fs-shadow);
  }
  .count-card[aria-pressed='true'] {
    background: var(--fs-accent-soft);
    color: var(--fs-accent);
    outline: 2px solid var(--fs-accent);
    outline-offset: 1px;
  }
  .count-card[aria-pressed='true'] .count-value {
    color: var(--fs-accent);
  }
  .count-value {
    font-size: 1.3rem;
    font-weight: 700;
    color: var(--fs-text);
  }
  .index-progress {
    display: grid;
    gap: 0.35rem;
    margin-bottom: 1rem;
    padding: 0.75rem 1rem;
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
  }
  .progress-head {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    color: var(--fs-muted);
    font-size: 0.85rem;
  }
  .progress-head strong {
    color: var(--fs-text);
  }
  .index-progress progress {
    appearance: none;
    width: 100%;
    height: 0.55rem;
    border: none;
    border-radius: 999px;
    overflow: hidden;
    background: var(--fs-bg);
  }
  .index-progress progress::-webkit-progress-bar {
    background: var(--fs-bg);
  }
  .index-progress progress::-webkit-progress-value {
    background: var(--fs-accent);
  }
  .index-progress progress::-moz-progress-bar {
    background: var(--fs-accent);
  }
  .progress-summary {
    margin: 0;
    color: var(--fs-muted);
    font-size: 0.8rem;
  }
  .indexing-now {
    display: grid;
    gap: 0.2rem;
  }
  .indexing-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.15rem;
    font-size: 0.8rem;
  }
  .aborted {
    display: grid;
    gap: 0.35rem;
    padding-top: 0.35rem;
    border-top: 1px solid var(--fs-border);
  }
  .aborted .indexing-list {
    max-height: 14rem;
    overflow-y: auto;
  }
  .aborted-item {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 0.75rem;
    align-items: flex-start;
    justify-content: space-between;
  }
  .aborted-copy {
    display: grid;
    gap: 0.1rem;
    min-width: 0;
  }
  .restart-button {
    padding: 0.35rem 0.7rem;
    border: none;
    border-radius: 0.4rem;
    font-weight: 600;
    white-space: nowrap;
    cursor: pointer;
  }
  .link-button {
    border: none;
    background: none;
    padding: 0;
    color: var(--fs-accent);
    font: inherit;
    text-align: left;
    text-decoration: underline;
    text-underline-offset: 0.15em;
    cursor: pointer;
  }
  .filters {
    display: flex;
    flex-wrap: wrap;
    gap: 0.55rem 0.7rem;
    align-items: end;
    margin-bottom: 0.9rem;
  }
  .filters label {
    display: grid;
    gap: 0.25rem;
    flex: 1 1 9rem;
    min-width: 8rem;
    font-size: 0.78rem;
    color: var(--fs-muted);
  }
  .filters label.search {
    flex: 2 1 16rem;
  }
  .filters input,
  .filters select,
  .list-head select,
  .approve-controls select,
  .actions select,
  .row-quality {
    padding: 0.42rem 0.55rem;
    font: inherit;
    border-radius: 0.4rem;
    border: 1px solid var(--fs-border);
    background: var(--fs-surface);
    color: var(--fs-text);
  }
  .filters input,
  .filters select {
    box-sizing: border-box;
    width: 100%;
    height: 2.4rem;
    padding: 0 0.55rem;
    font-size: 0.9rem;
  }
  .filters input[type='search'] {
    min-width: 0;
  }
  .filters button {
    height: 2.4rem;
    padding: 0 1rem;
    border: none;
    border-radius: 0.5rem;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }
  .split {
    display: grid;
    grid-template-columns: minmax(24rem, 32rem) minmax(0, 1fr);
    gap: 1rem;
    align-items: start;
  }
  @media (max-width: 900px) {
    .split {
      grid-template-columns: 1fr;
    }
  }
  .list,
  .detail {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1rem;
  }
  .list-head {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem 0.6rem;
    align-items: end;
    padding-bottom: 0.55rem;
    margin-bottom: 0.55rem;
    border-bottom: 1px solid color-mix(in srgb, var(--fs-border) 45%, transparent);
  }
  .select-all {
    display: inline-flex;
    gap: 0.4rem;
    align-items: center;
    font-size: 0.83rem;
    font-weight: 600;
    cursor: pointer;
  }
  .selected-count {
    color: var(--fs-muted);
    font-size: 0.78rem;
  }
  .bulk-quality {
    display: flex;
    gap: 0.4rem;
    align-items: end;
    margin-left: auto;
  }
  .bulk-quality label,
  .approval-quality {
    display: grid;
    gap: 0.2rem;
    font-size: 0.75rem;
    color: var(--fs-muted);
  }
  .bulk-quality select {
    min-width: 5.5rem;
  }
  .approve-controls {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem 0.6rem;
    align-items: end;
    padding-bottom: 0.6rem;
    margin-bottom: 0.4rem;
  }
  .approve-controls .confirm,
  .approve-controls .redistribution {
    margin-bottom: 0;
  }
  .approve-controls .approval-quality select {
    min-width: 7rem;
  }
  .list ul,
  .records {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    gap: 0.5rem;
  }
  .list li {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    gap: 0.5rem;
    align-items: start;
    border-radius: 0.6rem;
    padding: 0.5rem;
  }
  .list li.active {
    background: var(--fs-accent-soft);
  }
  .entry {
    background: none;
    border: none;
    padding: 0;
    min-width: 0;
    text-align: left;
    font: inherit;
    color: var(--fs-text);
    cursor: pointer;
    display: grid;
    gap: 0.2rem;
  }
  .title,
  .meta {
    overflow-wrap: anywhere;
  }
  .row-quality {
    width: 4.1rem;
  }
  .quality-readonly {
    min-width: 2.2rem;
    text-align: right;
    color: var(--fs-muted);
    font-size: 0.82rem;
    font-weight: 600;
  }
  .small {
    font-size: 0.8rem;
    margin: 0 0 0.4rem;
  }
  .title {
    font-weight: 600;
  }
  .meta {
    color: var(--fs-muted);
    font-size: 0.82rem;
  }
  .warn {
    color: var(--fs-false);
  }
  .preselect {
    color: var(--fs-accent);
    font-weight: 600;
  }
  .detail header h2 {
    margin: 0 0 0.2rem;
  }
  dl {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 0.3rem 1rem;
    font-size: 0.9rem;
  }
  dt {
    color: var(--fs-muted);
  }
  dd {
    margin: 0;
  }
  .warnings {
    background: var(--fs-warning-soft, #fdf6e3);
    border-radius: 0.6rem;
    padding: 0.6rem 0.8rem;
    margin: 0.8rem 0;
    color: var(--fs-text);
  }
  .figures,
  .content-block {
    margin-top: 1rem;
  }
  .figure {
    display: grid;
    gap: 0.4rem;
    background: var(--fs-bg);
    border-radius: 0.6rem;
    padding: 0.7rem;
    margin-bottom: 0.6rem;
  }
  .figure textarea {
    width: 100%;
    font: inherit;
    padding: 0.5rem;
    border-radius: 0.4rem;
    border: 1px solid var(--fs-border);
    background: var(--fs-surface);
    color: var(--fs-text);
  }
  .content-block pre {
    max-height: 24rem;
    overflow: auto;
    white-space: pre-wrap;
    background: var(--fs-bg);
    border-radius: 0.6rem;
    padding: 0.8rem;
    font-size: 0.85rem;
  }
  .actions {
    display: grid;
    gap: 0.4rem;
    margin-top: 0.9rem;
  }
  .actions input,
  .actions select,
  .redistribution select {
    width: 100%;
    padding: 0.5rem;
    font: inherit;
    border-radius: 0.4rem;
    border: 1px solid var(--fs-border);
    background: var(--fs-surface);
    color: var(--fs-text);
  }
  button {
    font: inherit;
  }
  .actions button,
  .list-head button,
  .approve-controls button {
    justify-self: start;
    padding: 0.45rem 0.9rem;
    border-radius: 0.5rem;
    border: none;
    background: var(--fs-accent);
    color: var(--fs-accent-contrast);
    font-weight: 600;
    cursor: pointer;
  }
  button:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
  button.ghost {
    background: var(--fs-accent-soft);
    color: var(--fs-accent);
  }
  button.danger {
    background: var(--fs-false);
    color: #fff;
  }
  .confirm,
  .redistribution {
    display: flex;
    gap: 0.45rem;
    align-items: center;
    font-size: 0.85rem;
    margin-bottom: 0.5rem;
  }
  .redistribution {
    justify-content: space-between;
  }
  .redistribution select {
    width: auto;
  }
  .records li {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 0.9rem 1rem;
  }
  .statement {
    font-weight: 600;
    margin: 0 0 0.25rem;
  }
  .buttons {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-top: 0.5rem;
  }
  .buttons button {
    padding: 0.4rem 0.8rem;
    border-radius: 0.5rem;
    border: none;
    font-weight: 600;
    cursor: pointer;
  }
  .error {
    color: var(--fs-false);
  }
  .ok {
    color: var(--fs-true);
  }
  .muted {
    color: var(--fs-muted);
  }
  .notice {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1rem;
  }
</style>
