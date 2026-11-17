<script lang="ts">
  import { onMount } from 'svelte';
  import {
    ApiError,
    getBudgets,
    getDataFlow,
    listRoles,
    setBudgets,
    setDataFlow,
    type DataFlowPolicy,
  } from '$lib/api';
  import { t } from '$lib/i18n';

  const tr = $derived($t);
  let policy = $state<DataFlowPolicy>({ allow_external: true, fallback_alias: null });
  let aliases = $state<string[]>([]);
  let budgets = $state<Record<string, string>>({});
  let error = $state('');
  let notice = $state('');
  let busy = $state(false);

  onMount(load);

  async function load(): Promise<void> {
    try {
      const [flow, roles, roleBudgets] = await Promise.all([
        getDataFlow(),
        listRoles(),
        getBudgets(),
      ]);
      policy = { allow_external: flow.allow_external, fallback_alias: flow.fallback_alias ?? null };
      aliases = roles.map((role) => role.alias);
      budgets = Object.fromEntries(
        aliases.map((alias) => [alias, (roleBudgets.roles ?? {})[alias]?.toString() ?? '']),
      );
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    }
  }

  async function save(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    busy = true;
    error = '';
    notice = '';
    try {
      await setDataFlow(policy);
      const values: Record<string, number> = {};
      for (const [alias, value] of Object.entries(budgets)) {
        if (value !== '') values[alias] = Number(value);
      }
      await setBudgets(values);
      notice = tr('admin.saved');
      await load();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = false;
    }
  }
</script>

<h1>{tr('admin.settings')}</h1>
{#if error}<p class="error" role="alert">{error}</p>{/if}
{#if notice}<p class="ok" role="status">{notice}</p>{/if}

<form onsubmit={save}>
  <section class="panel">
    <h2>{tr('admin.data_flow')}</h2>
    <label class="check">
      <input type="checkbox" bind:checked={policy.allow_external} />
      <span>{tr('admin.allow_external')}</span>
    </label>
    <label class="block">
      <span>{tr('admin.fallback')}</span>
      <select bind:value={policy.fallback_alias}>
        <option value={null}>{tr('admin.none')}</option>
        {#each aliases as alias}<option value={alias}>{alias}</option>{/each}
      </select>
    </label>
    <p class="hint">{tr('admin.data_flow_hint')}</p>
  </section>

  <section class="panel">
    <h2>{tr('admin.budgets')}</h2>
    <div class="budgets">
      {#each aliases as alias}
        <label>
          <span>{alias}</span>
          <input type="number" min="0" step="0.01" bind:value={budgets[alias]} placeholder="∞" />
        </label>
      {/each}
    </div>
    <p class="hint">{tr('admin.budgets_hint')}</p>
  </section>

  <button type="submit" disabled={busy}>{tr('admin.save')}</button>
</form>

<style>
  .panel {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1.2rem 1.35rem;
    margin-bottom: 1rem;
  }
  h2 {
    margin: 0 0 0.9rem;
    font-size: 1rem;
  }
  .check {
    display: flex;
    gap: 0.5rem;
    align-items: center;
    margin-bottom: 0.9rem;
  }
  .block {
    display: grid;
    gap: 0.3rem;
    max-width: 18rem;
    font-size: 0.85rem;
    margin-bottom: 0.75rem;
  }
  .budgets {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
    gap: 0.75rem;
  }
  .budgets label {
    display: grid;
    gap: 0.25rem;
    font-size: 0.85rem;
  }
  input,
  select {
    padding: 0.5rem 0.65rem;
    border-radius: 0.5rem;
    border: 1px solid color-mix(in srgb, var(--fs-border) 60%, transparent);
    background: var(--fs-bg);
    color: var(--fs-text);
    font: inherit;
  }
  input[type='checkbox'] {
    width: auto;
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
    opacity: 0.6;
    cursor: wait;
  }
  .hint {
    color: var(--fs-muted);
    font-size: 0.85rem;
    margin: 0.5rem 0 0;
  }
  .error {
    color: var(--fs-false);
  }
  .ok {
    color: var(--fs-true);
  }
</style>
