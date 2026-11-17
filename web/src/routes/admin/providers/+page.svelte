<script lang="ts">
  import { onMount } from 'svelte';
  import {
    ApiError,
    listModels,
    listProviders,
    testProvider,
    updateProvider,
    type ModelInfo,
    type ProviderInfo,
  } from '$lib/api';
  import { t } from '$lib/i18n';

  const tr = $derived($t);
  let providers = $state<ProviderInfo[]>([]);
  let models = $state<ModelInfo[]>([]);
  let error = $state('');
  let notice = $state('');
  let busy = $state('');
  let selected = $state('');
  let newKey = $state('');

  onMount(load);

  async function load(): Promise<void> {
    error = '';
    try {
      [providers, models] = await Promise.all([listProviders(), listModels()]);
      if (!selected && providers.length > 0) selected = providers[0]!.id;
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    }
  }

  async function test(id: string): Promise<void> {
    busy = id;
    error = '';
    notice = '';
    try {
      const result = await testProvider(id);
      notice = `${tr('admin.provider_ok')}: ${result.models.length} ${tr('admin.models')} · ${result.latency_ms} ms`;
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function replaceKey(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (!selected || !newKey) return;
    busy = 'key';
    error = '';
    notice = '';
    try {
      await updateProvider(selected, { api_key: newKey });
      newKey = '';
      notice = tr('admin.key_updated');
      await load();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }
</script>

<h1>{tr('admin.providers')}</h1>
{#if error}<p class="error" role="alert">{error}</p>{/if}
{#if notice}<p class="ok" role="status">{notice}</p>{/if}

<section class="panel">
  <h2>{tr('admin.providers')}</h2>
  <table>
    <thead>
      <tr>
        <th>{tr('admin.name')}</th><th>URL</th><th>{tr('admin.local')}</th
        ><th>{tr('admin.has_key')}</th><th></th>
      </tr>
    </thead>
    <tbody>
      {#each providers as provider}
        <tr>
          <td>{provider.name}</td>
          <td class="mono">{provider.base_url}</td>
          <td>{provider.is_local ? tr('common.yes') : tr('common.no')}</td>
          <td>{provider.has_key ? tr('common.yes') : tr('common.no')}</td>
          <td class="right">
            <button type="button" onclick={() => test(provider.id)} disabled={busy === provider.id}>
              {tr('admin.test_connection')}
            </button>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</section>

<section class="panel">
  <h2>{tr('admin.replace_key')}</h2>
  <form class="row" onsubmit={replaceKey}>
    <label>
      <span>{tr('admin.provider')}</span>
      <select bind:value={selected}>
        {#each providers as provider}
          <option value={provider.id}>{provider.name}</option>
        {/each}
      </select>
    </label>
    <label>
      <span>{tr('admin.api_key')}</span>
      <input type="password" bind:value={newKey} autocomplete="off" required />
    </label>
    <button type="submit" disabled={busy === 'key'}>{tr('admin.save')}</button>
  </form>
  <p class="hint">{tr('admin.key_hint')}</p>
</section>

<section class="panel">
  <h2>{tr('admin.models')}</h2>
  <table>
    <thead>
      <tr>
        <th>{tr('admin.model')}</th><th>{tr('admin.role')}</th><th>{tr('admin.capabilities')}</th
        ><th>{tr('admin.tested')}</th><th>{tr('admin.local')}</th>
      </tr>
    </thead>
    <tbody>
      {#each models as model}
        <tr>
          <td>{model.model_name}</td>
          <td class="mono">{model.gateway_alias ?? '—'}</td>
          <td>{(model.capabilities ?? []).join(', ')}</td>
          <td>{(model.tested_capabilities ?? []).join(', ') || '—'}</td>
          <td>{model.is_local ? tr('common.yes') : tr('common.no')}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</section>

<style>
  .panel {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1.2rem 1.35rem;
    margin-bottom: 1.25rem;
    overflow-x: auto;
  }
  h2 {
    font-size: 1rem;
    margin: 0 0 0.75rem;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
  }
  th {
    text-align: left;
    color: var(--fs-muted);
    font-weight: 600;
    padding: 0.3rem 0.5rem;
    white-space: nowrap;
  }
  td {
    padding: 0.45rem 0.5rem;
    border-top: 1px solid color-mix(in srgb, var(--fs-border) 45%, transparent);
  }
  .right {
    text-align: right;
  }
  .mono {
    font-family: ui-monospace, SFMono-Regular, monospace;
    font-size: 0.82rem;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    align-items: end;
  }
  label {
    display: grid;
    gap: 0.3rem;
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
  button:disabled {
    opacity: 0.6;
    cursor: wait;
  }
  .hint {
    color: var(--fs-muted);
    font-size: 0.85rem;
    margin: 0.75rem 0 0;
  }
  .error {
    color: var(--fs-false);
  }
  .ok {
    color: var(--fs-true);
  }
</style>
