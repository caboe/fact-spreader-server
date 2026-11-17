<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { page } from '$app/stores';
  import { ApiError, getJob, type JobEnvelope } from '$lib/api';
  import Report from '$lib/Report.svelte';
  import { t } from '$lib/i18n';
  const tr = $derived($t);

  let envelope = $state<JobEnvelope | null>(null);
  let error = $state('');
  let timer: ReturnType<typeof setTimeout> | null = null;
  const jobId = $derived($page.params.jobId ?? '');

  onMount(load);
  onDestroy(() => {
    if (timer) clearTimeout(timer);
  });

  async function load(): Promise<void> {
    try {
      envelope = await getJob(jobId);
      if (envelope.job.state === 'queued' || envelope.job.state === 'running') {
        timer = setTimeout(load, 1200);
      }
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    }
  }
</script>

<svelte:head><title>{tr('report.title')} · Fact Spreader</title></svelte:head>

<h1>{tr('report.title')}</h1>

{#if error}
  <p class="error" role="alert">{error}</p>
{:else if !envelope}
  <p>{tr('common.loading')}</p>
{:else if envelope.result}
  <Report response={envelope.result} />
{:else}
  <p aria-live="polite">
    {tr('state.' + envelope.job.state)} · {Math.round(envelope.job.progress * 100)}%
  </p>
  <progress value={envelope.job.progress} max="1"></progress>
{/if}

<style>
  .error {
    color: var(--fs-false);
  }
</style>
