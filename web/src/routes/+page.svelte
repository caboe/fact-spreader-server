<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import {
    ApiError,
    createCheck,
    getSession,
    listPersonas,
    type CheckInput,
    type Job,
  } from '$lib/api';
  import { session } from '$lib/session';
  import { t } from '$lib/i18n';
  const tr = $derived($t);

  type Mode = 'text' | 'url' | 'file' | 'image';

  let mode = $state<Mode>('text');
  let text = $state('');
  let url = $state('');
  let file = $state<File | null>(null);
  let persona = $state('factcheck:analyst');
  let language = $state('');
  let personas = $state<{ id: string; label: string }[]>([]);
  let busy = $state(false);
  let error = $state('');
  let job = $state<Job | null>(null);
  let progress = $state(0);
  let statements = $state<string[]>([]);
  let source: EventSource | null = null;

  onMount(async () => {
    if (!$session) {
      try {
        session.set(await getSession());
      } catch {
        session.set(null);
      }
    }
    personas = await listPersonas().catch(() => []);
  });
  onDestroy(() => source?.close());

  function chooseMode(next: Mode): void {
    mode = next;
    error = '';
  }

  function pickFile(event: Event): void {
    file = (event.currentTarget as HTMLInputElement).files?.[0] ?? null;
  }

  function listen(jobId: string): void {
    source?.close();
    source = new EventSource(`/v1/factcheck/${encodeURIComponent(jobId)}/events`);
    source.addEventListener('state', (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as {
        state: string;
        progress: number;
      };
      progress = payload.progress ?? 0;
      if (payload.state === 'failed') {
        error = tr('check.failed');
        source?.close();
      }
    });
    source.addEventListener('statement', (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as { text?: string };
      if (payload.text) statements = [...statements, payload.text];
    });
    source.addEventListener('done', () => {
      source?.close();
      goto(`/report/${encodeURIComponent(jobId)}`);
    });
    source.onerror = () => {
      /* EventSource reconnects; the report page also polls. */
    };
  }

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    error = '';
    statements = [];
    if (!$session) {
      error = tr('check.requires_login');
      return;
    }
    busy = true;
    try {
      const input: CheckInput =
        mode === 'text'
          ? { type: 'text', text }
          : mode === 'url'
            ? { type: 'url', url }
            : { type: mode };
      const personaId = persona === 'factcheck:none' ? null : persona.split(':')[1] ?? null;
      const result = await createCheck(
        {
          input,
          persona_id: personaId,
          response_language: language || null,
          mode: 'async',
        },
        mode === 'file' || mode === 'image' ? file : null,
      );
      job = result.job;
      progress = 0;
      listen(result.job.id);
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>{tr('check.title')} · Fact Spreader</title></svelte:head>

<section class="intro">
  <h1>{tr('check.title')}</h1>
  <p>{tr('check.intro')}</p>
</section>

<form class="checker" onsubmit={submit}>
  <div class="modes" role="group" aria-label={tr('check.title')}>
    {#each ['text', 'url', 'file', 'image'] as candidate}
      <button
        type="button"
        class:active={mode === candidate}
        aria-pressed={mode === candidate}
        onclick={() => chooseMode(candidate as Mode)}
      >
        {tr(`check.${candidate}`)}
      </button>
    {/each}
  </div>

  {#if mode === 'text'}
    <label class="field">
      <span>{tr('check.text')}</span>
      <textarea rows="6" bind:value={text} placeholder={tr('check.placeholder')} required></textarea>
    </label>
  {:else if mode === 'url'}
    <label class="field">
      <span>{tr('check.url')}</span>
      <input type="url" bind:value={url} placeholder={tr('check.url_placeholder')} required />
    </label>
  {:else}
    <label class="field">
      <span>{tr(`check.${mode}`)}</span>
      <input
        type="file"
        accept={mode === 'image' ? 'image/*' : undefined}
        onchange={pickFile}
        required
      />
    </label>
  {/if}

  <div class="row">
    <label class="field compact">
      <span>{tr('check.persona')}</span>
      <select bind:value={persona}>
        {#each personas as option}
          <option value={option.id}>{option.label}</option>
        {/each}
        <option value="factcheck:none">{tr('report.substance')}</option>
      </select>
    </label>
    <label class="field compact">
      <span>{tr('check.language')}</span>
      <select bind:value={language}>
        <option value="">auto</option>
        <option value="en">en</option>
        <option value="de">de</option>
        <option value="fr">fr</option>
        <option value="es">es</option>
      </select>
    </label>
  </div>

  {#if error}<p class="error" role="alert">{error}</p>{/if}
  <button class="submit" type="submit" disabled={busy}>
    {busy ? tr('check.running') : tr('check.submit')}
  </button>
</form>

{#if job}
  <section class="progress" aria-live="polite">
    <h2>{tr('check.running')}</h2>
    <p>
      {tr('state.' + job.state)} · {tr('check.progress')} {Math.round(progress * 100)}%
    </p>
    <progress value={progress} max="1"></progress>
    {#if statements.length > 0}
      <h3>{tr('check.statements')}</h3>
      <ul>
        {#each statements as statement}
          <li>{statement}</li>
        {/each}
      </ul>
    {/if}
  </section>
{/if}

<style>
  .intro {
    max-width: 48rem;
    margin-bottom: 1.25rem;
  }
  .checker {
    display: grid;
    gap: 1rem;
    max-width: 48rem;
    background: var(--fs-surface);
    border: 1px solid var(--fs-border);
    border-radius: var(--fs-radius);
    padding: 1.25rem;
  }
  .modes {
    display: flex;
    gap: 0.35rem;
    flex-wrap: wrap;
  }
  .modes button {
    border: 1px solid var(--fs-border);
    background: var(--fs-bg);
    color: var(--fs-text);
    border-radius: 999px;
    padding: 0.35rem 0.8rem;
    font: inherit;
    cursor: pointer;
  }
  .modes button.active {
    border-color: var(--fs-accent);
    font-weight: 700;
    text-decoration: underline;
  }
  .field {
    display: grid;
    gap: 0.35rem;
  }
  .field > span {
    font-size: 0.85rem;
    color: var(--fs-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  textarea,
  input,
  select {
    padding: 0.6rem 0.7rem;
    border-radius: 0.5rem;
    border: 1px solid var(--fs-border);
    background: var(--fs-bg);
    color: var(--fs-text);
    font: inherit;
    width: 100%;
    box-sizing: border-box;
  }
  .row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
  }
  .submit {
    justify-self: start;
    padding: 0.65rem 1.4rem;
    border-radius: 0.5rem;
    border: none;
    background: var(--fs-accent);
    color: #fff;
    font: inherit;
    font-weight: 700;
    cursor: pointer;
  }
  .submit:disabled {
    opacity: 0.6;
    cursor: wait;
  }
  .error {
    color: var(--fs-false);
    margin: 0;
  }
  .progress {
    margin-top: 1.5rem;
    max-width: 48rem;
  }
  progress {
    width: 100%;
  }
  @media (max-width: 40rem) {
    .row {
      grid-template-columns: 1fr;
    }
  }
</style>
