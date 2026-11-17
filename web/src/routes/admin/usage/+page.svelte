<script lang="ts">
  import { onMount } from 'svelte';
  import { ApiError, usageSummary, type UsageSummary } from '$lib/api';
  import { t } from '$lib/i18n';

  const tr = $derived($t);
  const today = new Date().toISOString().slice(0, 10);
  const monthStart = `${today.slice(0, 7)}-01`;
  let from = $state(monthStart);
  let to = $state(today);
  let summary = $state<UsageSummary | null>(null);
  let error = $state('');
  let loading = $state(false);
  const num = (value: unknown): number => (typeof value === 'number' ? value : Number(value ?? 0));

  onMount(load);

  async function load(): Promise<void> {
    loading = true;
    error = '';
    try {
      summary = await usageSummary(from, to);
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      loading = false;
    }
  }

  async function download(): Promise<void> {
    const response = await fetch(`/v1/usage/summary.csv?from=${from}&to=${to}`, {
      credentials: 'include',
    });
    if (!response.ok) {
      error = tr('common.error');
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `usage-${from}-${to}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }
</script>

<h1>{tr('admin.usage')}</h1>

<form class="filters" onsubmit={(event) => (event.preventDefault(), load())}>
  <label><span>{tr('admin.from')}</span><input type="date" bind:value={from} /></label>
  <label><span>{tr('admin.to')}</span><input type="date" bind:value={to} /></label>
  <button type="submit">{tr('admin.refresh')}</button>
  <button type="button" class="ghost" onclick={download}>{tr('admin.csv')}</button>
</form>

{#if error}<p class="error" role="alert">{error}</p>{/if}
{#if loading}<p>{tr('common.loading')}</p>{/if}

{#if summary}
  <div class="cards">
    <div class="card"><strong>{num(summary.totals.calls)}</strong><span>{tr('admin.calls')}</span></div>
    <div class="card"><strong>{num(summary.totals.tokens_in) + num(summary.totals.tokens_out)}</strong><span>tokens</span></div>
    <div class="card"><strong>${num(summary.totals.cost_usd).toFixed(4)}</strong><span>USD</span></div>
  </div>

  <section class="panel">
    <h2>{tr('admin.by_consumer')}</h2>
    <table>
      <thead><tr><th>{tr('admin.consumer')}</th><th>{tr('admin.calls')}</th><th>tokens</th><th>USD</th></tr></thead>
      <tbody>
        {#each summary.breakdowns?.consumer ?? [] as row}
          <tr><td>{row.key}</td><td>{num(row.calls)}</td><td>{num(row.tokens_in) + num(row.tokens_out)}</td><td>{num(row.cost_usd).toFixed(5)}</td></tr>
        {/each}
      </tbody>
    </table>
  </section>

  <section class="panel">
    <h2>{tr('admin.by_role')}</h2>
    <table>
      <thead><tr><th>{tr('admin.role')}</th><th>{tr('admin.calls')}</th><th>tokens</th><th>USD</th></tr></thead>
      <tbody>
        {#each summary.breakdowns?.role ?? [] as row}
          <tr><td>{row.key}</td><td>{num(row.calls)}</td><td>{num(row.tokens_in) + num(row.tokens_out)}</td><td>{num(row.cost_usd).toFixed(5)}</td></tr>
        {/each}
      </tbody>
    </table>
  </section>

  <section class="panel">
    <h2>{tr('admin.daily')}</h2>
    <table>
      <thead><tr><th>{tr('admin.date')}</th><th>{tr('admin.calls')}</th><th>USD</th></tr></thead>
      <tbody>
        {#each summary.series as row}
          <tr><td>{row.date}</td><td>{num(row.calls)}</td><td>{num(row.cost_usd).toFixed(5)}</td></tr>
        {/each}
      </tbody>
    </table>
  </section>
{/if}

<style>
  .filters {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    align-items: end;
    margin-bottom: 1.25rem;
  }
  label {
    display: grid;
    gap: 0.25rem;
    font-size: 0.85rem;
  }
  input {
    padding: 0.5rem 0.65rem;
    border-radius: 0.5rem;
    border: 1px solid color-mix(in srgb, var(--fs-border) 60%, transparent);
    background: var(--fs-bg);
    color: var(--fs-text);
    font: inherit;
  }
  button {
    padding: 0.5rem 0.9rem;
    border-radius: 0.5rem;
    border: none;
    background: var(--fs-accent);
    color: var(--fs-accent-contrast);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }
  button.ghost {
    background: var(--fs-bg);
    color: var(--fs-text);
    box-shadow: var(--fs-shadow-soft);
  }
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
    gap: 1rem;
    margin-bottom: 1.25rem;
  }
  .card {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1rem 1.15rem;
    display: grid;
    gap: 0.2rem;
  }
  .card strong {
    font-size: 1.5rem;
    color: var(--fs-accent);
  }
  .card span {
    color: var(--fs-muted);
    font-size: 0.85rem;
  }
  .panel {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1.1rem 1.25rem;
    margin-bottom: 1rem;
    overflow-x: auto;
  }
  h2 {
    margin: 0 0 0.6rem;
    font-size: 1rem;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
  }
  th {
    text-align: left;
    color: var(--fs-muted);
    padding: 0.3rem 0.5rem;
  }
  td {
    padding: 0.4rem 0.5rem;
    border-top: 1px solid color-mix(in srgb, var(--fs-border) 45%, transparent);
  }
  .error {
    color: var(--fs-false);
  }
</style>
