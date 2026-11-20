<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import {
    ApiError,
    getSession,
    rawRetrieval,
    type RawRetrievalResponse,
    type RetrievalMode,
  } from '$lib/api';
  import { session } from '$lib/session';
  import { t } from '$lib/i18n';

  const tr = $derived($t);
  const MODES: RetrievalMode[] = ['mix', 'local', 'global', 'hybrid', 'naive'];
  const MODE_LABELS: Record<RetrievalMode, string> = {
    mix: 'Mix',
    local: 'Local',
    global: 'Global',
    hybrid: 'Hybrid',
    naive: 'Naive',
  };

  let query = $state('');
  let mode = $state<RetrievalMode>('mix');
  // The diagnostic default is deliberately lower than the check pipeline's graph breadth:
  // graph candidates share LightRAG's context budget with the passages they crowd out.
  let topK = $state(10);
  let chunkTopK = $state(20);
  let includeGraph = $state(true);
  let result = $state<RawRetrievalResponse | null>(null);
  let error = $state('');
  let busy = $state(false);

  const canUse = $derived(Boolean($session?.user.permissions.includes('search:use')));
  const documents = $derived(result?.documents ?? []);
  const entities = $derived(result?.entities ?? []);
  const relationships = $derived(result?.relationships ?? []);

  onMount(async () => {
    if (!$session) {
      try {
        session.set(await getSession());
      } catch {
        session.set(null);
      }
    }
    if (!$session) await goto('/login');
  });

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (!query.trim() || busy) return;
    error = '';
    result = null;
    busy = true;
    try {
      result = await rawRetrieval({
        query: query.trim(),
        mode,
        top_k: topK,
        chunk_top_k: chunkTopK,
        include_graph: includeGraph,
      });
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) {
        error = tr('raw.forbidden');
      } else if (cause instanceof ApiError && cause.status === 503) {
        error = cause.message;
      } else {
        error = tr('raw.failed');
      }
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>{tr('raw.title')} · Fact Spreader</title></svelte:head>

<section class="intro">
  <h1>{tr('raw.title')}</h1>
  <p>{tr('raw.intro')}</p>
  <p class="warning" role="note">{tr('raw.not_a_check')}</p>
</section>

{#if !$session}
  <p class="notice">{tr('common.loading')}</p>
{:else if !canUse}
  <p class="notice">{tr('raw.forbidden')}</p>
{:else}
  <form class="panel" onsubmit={submit}>
    <label class="query">
      <span>{tr('raw.query')}</span>
      <textarea
        bind:value={query}
        rows="3"
        maxlength="2000"
        placeholder={tr('raw.query_placeholder')}
        required
      ></textarea>
    </label>
    <div class="options">
      <label>
        <span>{tr('raw.mode')}</span>
        <span class="select-control">
          <select bind:value={mode}>
            {#each MODES as item}
              <option value={item}>{MODE_LABELS[item]}</option>
            {/each}
          </select>
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M4 6l4 4 4-4" />
          </svg>
        </span>
      </label>
      <label>
        <span>{tr('raw.top_k')}</span>
        <input type="number" min="1" max="100" bind:value={topK} />
      </label>
      <label>
        <span>{tr('raw.chunk_top_k')}</span>
        <input type="number" min="1" max="100" bind:value={chunkTopK} />
      </label>
      <label class="checkbox">
        <input type="checkbox" bind:checked={includeGraph} />
        <span>{tr('raw.include_graph')}</span>
      </label>
    </div>
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    <button type="submit" disabled={busy || !query.trim()}>
      {busy ? tr('raw.running') : tr('raw.submit')}
    </button>
  </form>

  {#if result}
    <section class="results" aria-live="polite" aria-busy={busy}>
      <div class="result-meta">
        <p>
          {tr('raw.summary', {
            documents: documents.length,
            chunks: result.returned_chunks,
            ms: result.took_ms,
          })}
        </p>
        <p class="filtered relevance">
          {tr('raw.relevance', {
            floor: result.relevance.floor.toFixed(2),
            margin: result.relevance.margin.toFixed(2),
            top: result.relevance.top_score == null ? '–' : result.relevance.top_score.toFixed(3),
            chunks: result.relevance.cut_chunks,
            entities: result.relevance.cut_entities,
            relationships: result.relevance.cut_relationships,
          })}
        </p>
        {#if result.dropped_chunks || result.dropped_entities || result.dropped_relationships}
          <p class="filtered">
            {tr('raw.filtered', {
              chunks: result.dropped_chunks,
              entities: result.dropped_entities,
              relationships: result.dropped_relationships,
            })}
          </p>
        {/if}
      </div>

      {#if documents.length === 0}
        <p class="empty">{tr('raw.empty')}</p>
      {/if}

      {#each documents as item (item.document.id + '@' + item.document.version)}
        <article class="document">
          <header>
            <h2>
              {#if item.document.url}
                <a href={item.document.url} target="_blank" rel="noreferrer"
                  >{item.document.title}</a
                >
              {:else}
                {item.document.title}
              {/if}
            </h2>
            <p class="meta">
              <span>{item.document.publisher}</span>
              {#if item.document.publication_date}
                <span>· {item.document.publication_date}</span>
              {/if}
              <span>· {tr('editorial.source_quality')} {item.document.source_quality}</span>
              <span>· {item.document.language}</span>
              {#if item.document.license}<span>· {item.document.license}</span>{/if}
              <span>· v{item.document.version}</span>
            </p>
          </header>
          {#each item.chunks as chunk}
            <div class="chunk">
              <p>{chunk.content}</p>
              <p class="chunk-meta">
                {#if chunk.reference_id}<span>#{chunk.reference_id}</span>{/if}
                {#if chunk.chunk_id}<code>{chunk.chunk_id}</code>{/if}
                {#if chunk.score != null}<span>· {chunk.score.toFixed(3)}</span>{/if}
              </p>
            </div>
          {/each}
        </article>
      {/each}

      {#if entities.length || relationships.length}
        <details class="graph">
          <summary>
            {tr('raw.graph', {
              entities: entities.length,
              relationships: relationships.length,
            })}
          </summary>
          <pre>{JSON.stringify({ entities, relationships }, null, 2)}</pre>
        </details>
      {/if}

      <details class="json">
        <summary>{tr('raw.response_json')}</summary>
        <pre>{JSON.stringify(result, null, 2)}</pre>
      </details>
    </section>
  {/if}
{/if}

<style>
  .intro {
    max-width: 52rem;
  }
  .intro h1 {
    margin-bottom: 0.4rem;
  }
  .intro p {
    margin: 0.4rem 0;
  }
  .warning {
    border-left: 4px solid var(--fs-accent);
    border-radius: 0.4rem;
    background: var(--fs-accent-soft);
    color: var(--fs-text);
    padding: 0.6rem 0.8rem;
    font-size: 0.9rem;
  }
  .notice,
  .empty {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1rem;
  }
  .panel,
  .document,
  .graph,
  .json {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
  }
  .panel {
    /* One control height keeps selects, number inputs and the submit button on the
       same line, independent of the browser's intrinsic select metrics. */
    --control-height: 2.75rem;
    display: grid;
    gap: 0.9rem;
    padding: 1.1rem 1.25rem;
    margin-top: 1rem;
  }
  label {
    display: grid;
    gap: 0.3rem;
    font-size: 0.85rem;
    color: var(--fs-muted);
  }
  textarea,
  select,
  input[type='number'] {
    width: 100%;
    padding: 0.55rem 0.65rem;
    border: 1px solid var(--fs-border);
    border-radius: 0.5rem;
    background: var(--fs-bg);
    color: var(--fs-text);
    font: inherit;
    font-size: 0.9rem;
  }
  select,
  input[type='number'] {
    height: var(--control-height);
  }
  select {
    appearance: none;
    /* Room for the chevron below, which replaces the browser's edge-hugging arrow. */
    padding: 0 2.25rem 0 0.65rem;
  }
  .select-control {
    position: relative;
    display: block;
  }
  .select-control svg {
    position: absolute;
    top: 50%;
    right: 0.9rem;
    width: 0.8rem;
    height: 0.8rem;
    transform: translateY(-50%);
    fill: none;
    stroke: var(--fs-muted);
    stroke-width: 1.7;
    stroke-linecap: round;
    stroke-linejoin: round;
    pointer-events: none;
  }
  textarea {
    resize: vertical;
  }
  .options {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
    gap: 0.75rem;
    align-items: end;
  }
  .checkbox {
    display: flex;
    gap: 0.45rem;
    align-items: center;
    padding-bottom: 0.55rem;
    color: var(--fs-text);
  }
  .checkbox input {
    width: auto;
  }
  button {
    justify-self: start;
    height: var(--control-height);
    padding: 0 1rem;
    border: none;
    border-radius: 0.5rem;
    background: var(--fs-accent);
    color: var(--fs-accent-contrast);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }
  button:disabled {
    opacity: 0.55;
    cursor: wait;
  }
  .error {
    margin: 0;
    color: var(--fs-false);
  }
  .results {
    display: grid;
    gap: 1rem;
    margin-top: 1.25rem;
  }
  .result-meta {
    display: grid;
    gap: 0.25rem;
    color: var(--fs-muted);
    font-size: 0.88rem;
  }
  .result-meta p {
    margin: 0;
  }
  .filtered {
    font-size: 0.8rem;
  }
  .document {
    padding: 1.1rem 1.25rem;
  }
  .document h2 {
    margin: 0 0 0.25rem;
    font-size: 1.05rem;
  }
  .meta,
  .chunk-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem;
    color: var(--fs-muted);
    font-size: 0.8rem;
  }
  .meta {
    margin: 0;
  }
  .chunk {
    margin-top: 0.8rem;
    padding-top: 0.8rem;
    border-top: 1px solid var(--fs-border);
  }
  .chunk p {
    margin: 0 0 0.35rem;
    white-space: pre-wrap;
  }
  .chunk-meta code {
    font-size: 0.75rem;
  }
  .graph,
  .json {
    padding: 0.9rem 1rem;
  }
  summary {
    cursor: pointer;
    font-weight: 600;
  }
  pre {
    max-height: 32rem;
    overflow: auto;
    margin: 0.8rem 0 0;
    padding: 0.8rem;
    border-radius: 0.5rem;
    background: var(--fs-bg);
    font-size: 0.76rem;
    line-height: 1.45;
  }
</style>
