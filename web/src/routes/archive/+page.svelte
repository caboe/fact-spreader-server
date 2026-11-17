<script lang="ts">
  import { onMount } from 'svelte';
  import { ApiError, getSession, listClaims } from '$lib/api';
  import { session } from '$lib/session';
  import { t } from '$lib/i18n';
  const tr = $derived($t);

  interface Entry {
    result_id: string;
    claim_text: string;
    overall_verdict: string | null;
    language: string;
    created_at: string;
    preliminary: boolean;
    has_contradiction: boolean;
  }

  let entries = $state<Entry[]>([]);
  let query = $state('');
  let mine = $state(true);
  let error = $state('');
  let loading = $state(true);

  onMount(load);

  async function load(): Promise<void> {
    loading = true;
    error = '';
    try {
      if (!$session) session.set(await getSession());
      const payload = await listClaims({ query: query || undefined, mine });
      entries = payload.data as Entry[];
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        error = tr('check.requires_login');
      } else {
        error = cause instanceof ApiError ? cause.message : tr('common.error');
      }
    } finally {
      loading = false;
    }
  }

  function submit(event: SubmitEvent): void {
    event.preventDefault();
    void load();
  }
</script>

<svelte:head><title>{tr('archive.title')} · Fact Spreader</title></svelte:head>

<h1>{tr('archive.title')}</h1>

<form class="search" onsubmit={submit}>
  <label class="field">
    <span>{tr('archive.search')}</span>
    <input type="search" bind:value={query} />
  </label>
  <label class="mine">
    <input type="checkbox" bind:checked={mine} />
    <span>{tr('archive.mine')}</span>
  </label>
  <button type="submit">{tr('archive.search')}</button>
</form>

{#if error}
  <p class="error" role="alert">{error}</p>
{:else if loading}
  <p>{tr('common.loading')}</p>
{:else if entries.length === 0}
  <p>{tr('archive.empty')}</p>
{:else}
  <ul class="claims">
    {#each entries as entry}
      <li>
        <a href={`/claim/${entry.result_id}`}>{entry.claim_text}</a>
        <p class="meta">
          {entry.overall_verdict
            ? tr(`verdict.${entry.overall_verdict}`)
            : tr('report.verdict')} ·
          {entry.language} ·
          <time datetime={entry.created_at}>{new Date(entry.created_at).toLocaleDateString()}</time>
        </p>
      </li>
    {/each}
  </ul>
{/if}

<style>
  .search {
    display: flex;
    gap: 0.75rem;
    align-items: end;
    flex-wrap: wrap;
    margin-bottom: 1.25rem;
  }
  .field {
    display: grid;
    gap: 0.3rem;
  }
  .field span {
    font-size: 0.85rem;
    color: var(--fs-muted);
  }
  input[type='search'] {
    padding: 0.55rem 0.7rem;
    border-radius: 0.5rem;
    border: 1px solid var(--fs-border);
    background: var(--fs-bg);
    color: var(--fs-text);
    font: inherit;
    min-width: 18rem;
  }
  button {
    padding: 0.55rem 1rem;
    border-radius: 0.5rem;
    border: 1px solid var(--fs-border);
    background: var(--fs-surface);
    color: var(--fs-text);
    font: inherit;
    cursor: pointer;
  }
  .mine {
    display: flex;
    gap: 0.35rem;
    align-items: center;
  }
  .claims {
    list-style: none;
    padding: 0;
    display: grid;
    gap: 0.75rem;
  }
  .claims li {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1rem 1.15rem;
  }
  .claims a {
    font-weight: 600;
    text-decoration: none;
  }
  .meta {
    margin: 0.35rem 0 0;
    color: var(--fs-muted);
    font-size: 0.85rem;
  }
  .error {
    color: var(--fs-false);
  }
</style>
