<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { ApiError, getReindex, startReindex } from '$lib/api';
  import { t } from '$lib/i18n';

  const tr = $derived($t);
  let documents = $state(0);
  let confirmed = $state(false);
  let error = $state('');
  let job = $state<{ job_id: string; state: string; progress: number; documents: number } | null>(
    null,
  );
  let busy = $state(false);
  let timer: ReturnType<typeof setTimeout> | null = null;

  onMount(async () => {
    try {
      const response = await fetch('/v1/instance');
      if (response.ok) documents = ((await response.json()) as { document_count: number }).document_count;
    } catch {
      /* public endpoint unavailable */
    }
  });
  onDestroy(() => {
    if (timer) clearTimeout(timer);
  });

  async function start(): Promise<void> {
    busy = true;
    error = '';
    try {
      const accepted = await startReindex();
      job = { job_id: accepted.job_id, state: 'queued', progress: 0, documents: accepted.documents };
      poll(accepted.job_id);
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = false;
    }
  }

  async function poll(jobId: string): Promise<void> {
    try {
      job = await getReindex(jobId);
      if (job.state === 'queued' || job.state === 'running') {
        timer = setTimeout(() => poll(jobId), 1500);
      }
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    }
  }
</script>

<h1>{tr('admin.reindex')}</h1>
<p class="hint">{tr('admin.reindex_hint', { count: documents })}</p>

<section class="panel warn">
  <p>{tr('admin.reindex_warning')}</p>
  <label class="check">
    <input type="checkbox" bind:checked={confirmed} />
    <span>{tr('admin.confirm_reindex')}</span>
  </label>
  <button type="button" onclick={start} disabled={!confirmed || busy || documents === 0}>
    {tr('admin.start_reindex')}
  </button>
</section>

{#if error}<p class="error" role="alert">{error}</p>{/if}

{#if job}
  <section class="panel" aria-live="polite">
    <h2>{tr('admin.reindex_job')}</h2>
    <p><code>{job.job_id}</code></p>
    <p>{tr('admin.job_state')}: {job.state} · {tr('admin.progress')}: {Math.round(job.progress * 100)}%</p>
    <progress value={job.progress} max="1"></progress>
    <p>{tr('admin.documents')}: {job.documents}</p>
  </section>
{/if}

<style>
  .panel {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1.2rem 1.35rem;
    margin-bottom: 1rem;
    max-width: 46rem;
  }
  .warn {
    box-shadow: inset 4px 0 0 var(--fs-misleading), var(--fs-shadow-soft);
  }
  .check {
    display: flex;
    gap: 0.5rem;
    align-items: center;
    margin: 0.75rem 0;
  }
  button {
    padding: 0.55rem 1.1rem;
    border-radius: 0.5rem;
    border: none;
    background: var(--fs-accent);
    color: var(--fs-accent-contrast);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }
  button:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
  progress {
    width: 100%;
  }
  code {
    font-size: 0.85rem;
  }
  .hint {
    color: var(--fs-muted);
  }
  .error {
    color: var(--fs-false);
  }
</style>
