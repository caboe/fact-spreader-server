<script lang="ts">
  import { onMount } from 'svelte';
  import {
    ApiError,
    type DocumentInfo,
    type EditorContradiction,
    type EditorGap,
    approveDocument,
    getDocument,
    getDocumentContent,
    listContradictions,
    listGaps,
    listReviewQueue,
    rejectDocument,
    recheckGap,
    updateContradiction,
    updateFigure,
    updateGap,
    withdrawDocument,
  } from '$lib/api';
  import { session } from '$lib/session';
  import { t } from '$lib/i18n';

  const tr = $derived($t);
  type Tab = 'queue' | 'contradictions' | 'gaps';

  let tab = $state<Tab>('queue');
  let queue = $state<DocumentInfo[]>([]);
  let counts = $state<Record<string, number>>({});
  let stateFilter = $state('');
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
  let note = $state('');
  let rejectReason = $state('');
  let withdrawReason = $state('');

  const canReview = $derived(
    Boolean($session?.user.permissions.includes('documents:review')),
  );
  const preselected = $derived(queue.filter((document) => document.approval_preselected));

  onMount(async () => {
    await Promise.all([loadQueue(), loadContradictions(), loadGaps()]);
  });

  async function loadQueue(): Promise<void> {
    error = '';
    try {
      const result = await listReviewQueue(stateFilter || undefined);
      queue = result.data;
      counts = result.counts;
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

  function toggle(document: DocumentInfo): void {
    selectedIds = selectedIds.includes(document.id)
      ? selectedIds.filter((id) => id !== document.id)
      : [...selectedIds, document.id];
  }

  function selectPreselected(): void {
    selectedIds = preselected.map((document) => document.id);
  }

  async function approveOne(id: string): Promise<void> {
    await approveDocument(id, {
      license_confirmed: true,
      redistribution,
      note: note || undefined,
    });
  }

  async function approve(): Promise<void> {
    if (!detail) return;
    if (!licenseConfirmed) {
      error = tr('editorial.license_required');
      return;
    }
    busy = 'approve';
    error = '';
    notice = '';
    try {
      detail = await approveDocument(detail.id, {
        license_confirmed: true,
        redistribution,
        note: note || undefined,
      });
      notice = tr('editorial.approved_ok');
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
    busy = 'batch';
    error = '';
    notice = '';
    try {
      let approved = 0;
      for (const id of selectedIds) {
        try {
          await approveOne(id);
          approved += 1;
        } catch (cause) {
          error = cause instanceof ApiError ? cause.message : tr('common.error');
        }
      }
      selectedIds = [];
      notice = tr('editorial.approved_count', { count: approved });
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
        <div class="count-card">
          <span class="count-value">{counts[key] ?? 0}</span>
          <span>{tr(`editorial.count_${key}`)}</span>
        </div>
      {/each}
    </section>

    <label class="filter">
      <span>{tr('editorial.filter')}</span>
      <select bind:value={stateFilter} onchange={loadQueue}>
        <option value="">{tr('editorial.filter_pending')}</option>
        <option value="approved">{tr('editorial.filter_approved')}</option>
        <option value="indexed">{tr('editorial.filter_indexed')}</option>
        <option value="rejected">{tr('editorial.filter_rejected')}</option>
        <option value="withdrawn">{tr('editorial.filter_withdrawn')}</option>
      </select>
    </label>

    <div class="split">
      <section class="list" aria-label={tr('editorial.queue')}>
        <div class="list-tools">
          <button
            type="button"
            class="ghost"
            onclick={selectPreselected}
            disabled={preselected.length === 0}
            >{tr('editorial.select_all')}</button
          >
          <button
            type="button"
            onclick={approveSelected}
            disabled={selectedIds.length === 0 || busy === 'batch'}
            >{tr('editorial.approve_selected')} ({selectedIds.length})</button
          >
        </div>
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
                <span>{tr('editorial.note')}</span>
                <input type="text" bind:value={note} />
              </label>
              <button type="button" onclick={approve} disabled={busy === 'approve' || !licenseConfirmed}>
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
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 0.7rem 0.9rem;
    display: grid;
    gap: 0.15rem;
    font-size: 0.85rem;
    color: var(--fs-muted);
  }
  .count-value {
    font-size: 1.3rem;
    font-weight: 700;
    color: var(--fs-text);
  }
  .filter {
    display: flex;
    gap: 0.5rem;
    align-items: center;
    margin-bottom: 0.8rem;
    font-size: 0.9rem;
    color: var(--fs-muted);
  }
  .filter select {
    padding: 0.4rem 0.6rem;
    font: inherit;
    border-radius: 0.4rem;
    border: 1px solid var(--fs-border);
    background: var(--fs-surface);
    color: var(--fs-text);
  }
  .split {
    display: grid;
    grid-template-columns: minmax(18rem, 24rem) minmax(0, 1fr);
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
  .list-tools {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-bottom: 0.7rem;
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
    display: flex;
    gap: 0.6rem;
    align-items: flex-start;
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
    text-align: left;
    font: inherit;
    color: var(--fs-text);
    cursor: pointer;
    display: grid;
    gap: 0.2rem;
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
  .list-tools button {
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
