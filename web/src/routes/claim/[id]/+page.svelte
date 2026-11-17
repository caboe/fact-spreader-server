<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { ApiError, getClaim, sendFeedback, type CheckResponse } from '$lib/api';
  import Report from '$lib/Report.svelte';
  import { t } from '$lib/i18n';
  const tr = $derived($t);

  interface Detail {
    result: CheckResponse;
    versions: { result_id: string; version: number; created_at: string; current: boolean }[];
    feedback: { helpful: number; unhelpful: number; incorrect: number; my_feedback: string | null };
  }

  let detail = $state<Detail | null>(null);
  let error = $state('');
  let feedbackSent = $state('');
  const resultId = $derived($page.params.id ?? '');

  onMount(load);

  async function load(): Promise<void> {
    try {
      detail = await getClaim(resultId);
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    }
  }

  async function feedback(kind: string): Promise<void> {
    try {
      await sendFeedback(resultId, kind);
      feedbackSent = kind;
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    }
  }
</script>

<svelte:head><title>{tr('report.title')} · Fact Spreader</title></svelte:head>

{#if error}
  <p class="error" role="alert">{error}</p>
{:else if !detail}
  <p>{tr('common.loading')}</p>
{:else}
  <Report response={detail.result} />
  <section class="archive-meta">
    <h2>{tr('archive.version')}</h2>
    <ol>
      {#each detail.versions as version}
        <li>
          <a href={`/claim/${version.result_id}`}>{tr('archive.version')} {version.version}</a>
          · <time datetime={version.created_at}
            >{new Date(version.created_at).toLocaleString()}</time
          >
          {#if version.current}<strong>({tr('report.verdict')} {tr('state.done')})</strong>{/if}
        </li>
      {/each}
    </ol>
    <h2>{tr('archive.feedback')}</h2>
    <div class="feedback">
      <button type="button" onclick={() => feedback('helpful')}>helpful</button>
      <button type="button" onclick={() => feedback('unhelpful')}>unhelpful</button>
      <button type="button" onclick={() => feedback('incorrect')}>incorrect</button>
    </div>
    {#if feedbackSent}<p role="status">✓ {feedbackSent}</p>{/if}
  </section>
{/if}

<style>
  .archive-meta {
    margin-top: 2rem;
    border-top: 1px solid var(--fs-border);
    padding-top: 1rem;
  }
  .feedback {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
  }
  .feedback button {
    padding: 0.4rem 0.9rem;
    border-radius: 0.5rem;
    border: 1px solid var(--fs-border);
    background: var(--fs-surface);
    color: var(--fs-text);
    font: inherit;
    cursor: pointer;
  }
  .error {
    color: var(--fs-false);
  }
</style>
