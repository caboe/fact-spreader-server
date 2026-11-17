<script lang="ts">
  import { onMount } from 'svelte';
  import { ApiError, assignRole, listModels, listRoles, type ModelInfo, type RoleInfo } from '$lib/api';
  import { t } from '$lib/i18n';

  const tr = $derived($t);
  let roles = $state<RoleInfo[]>([]);
  let models = $state<ModelInfo[]>([]);
  let choices = $state<Record<string, string>>({});
  let error = $state('');
  let notice = $state('');
  let busy = $state('');

  onMount(load);

  async function load(): Promise<void> {
    error = '';
    try {
      [roles, models] = await Promise.all([listRoles(), listModels()]);
      const base = models.filter((model) => model.gateway_alias === null && model.enabled);
      for (const role of roles) {
        choices[role.alias] = base.some((model) => model.id === role.model?.id)
          ? (role.model?.id ?? '')
          : (base[0]?.id ?? '');
      }
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    }
  }

  async function assign(alias: string): Promise<void> {
    const modelId = choices[alias];
    if (!modelId) return;
    busy = alias;
    error = '';
    notice = '';
    try {
      await assignRole(alias, modelId);
      notice = `${alias}: ${tr('admin.role_assigned')}`;
      await load();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }
</script>

<h1>{tr('admin.roles')}</h1>
<p class="hint">{tr('admin.roles_hint')}</p>
{#if error}<p class="error" role="alert">{error}</p>{/if}
{#if notice}<p class="ok" role="status">{notice}</p>{/if}

<div class="roles">
  {#each roles as role}
    <article class="panel">
      <header>
        <h2>{role.alias}</h2>
        <span class={role.suitable ? 'badge ok' : 'badge warn'}>
          {role.suitable ? tr('admin.suitable') : tr('admin.not_suitable')}
        </span>
      </header>
      <p class="label">{role.label}</p>
      <dl>
        <dt>{tr('admin.requires')}</dt>
        <dd>{(role.required_capabilities ?? []).join(', ')}</dd>
        {#if role.min_context}
          <dt>{tr('admin.min_context')}</dt>
          <dd>{role.min_context}</dd>
        {/if}
        <dt>{tr('admin.current_model')}</dt>
        <dd>{role.model ? `${role.model.model_name} (${role.model.gateway_alias})` : '—'}</dd>
      </dl>
      {#if (role.reasons ?? []).length > 0}
        <ul class="reasons">
          {#each role.reasons ?? [] as reason}
            <li>{reason}</li>
          {/each}
        </ul>
      {/if}
      <form onsubmit={(event) => (event.preventDefault(), assign(role.alias))}>
        <label>
          <span>{tr('admin.assign_model')}</span>
          <select bind:value={choices[role.alias]}>
            {#each models.filter((model) => model.gateway_alias === null && model.enabled) as model}
              <option value={model.id}
                >{model.model_name} · {(model.tested_capabilities ?? []).join(', ') || tr('admin.untested')}</option
              >
            {/each}
          </select>
        </label>
        <button type="submit" disabled={busy === role.alias || !choices[role.alias]}>
          {tr('admin.assign')}
        </button>
      </form>
    </article>
  {/each}
</div>

<style>
  .roles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr));
    gap: 1rem;
  }
  .panel {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1.1rem 1.2rem;
  }
  header {
    display: flex;
    gap: 0.75rem;
    align-items: center;
    justify-content: space-between;
  }
  h2 {
    margin: 0;
    font-size: 1.05rem;
  }
  .label {
    color: var(--fs-muted);
    margin: 0.15rem 0 0.75rem;
    font-size: 0.85rem;
  }
  dl {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.25rem 0.75rem;
    font-size: 0.85rem;
  }
  dt {
    color: var(--fs-muted);
  }
  dd {
    margin: 0;
  }
  .reasons {
    margin: 0.75rem 0;
    padding-left: 1.2rem;
    color: var(--fs-misleading);
    font-size: 0.85rem;
  }
  form {
    display: flex;
    gap: 0.5rem;
    align-items: end;
    margin-top: 0.75rem;
    flex-wrap: wrap;
  }
  label {
    display: grid;
    gap: 0.25rem;
    font-size: 0.8rem;
    color: var(--fs-muted);
    flex: 1;
  }
  select {
    padding: 0.45rem 0.6rem;
    border-radius: 0.5rem;
    border: 1px solid color-mix(in srgb, var(--fs-border) 60%, transparent);
    background: var(--fs-bg);
    color: var(--fs-text);
    font: inherit;
  }
  button {
    padding: 0.45rem 0.9rem;
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
  .badge {
    font-size: 0.75rem;
    padding: 0.15rem 0.5rem;
    border-radius: 999px;
    white-space: nowrap;
  }
  .badge.ok {
    background: color-mix(in srgb, var(--fs-true) 15%, transparent);
    color: var(--fs-true);
  }
  .badge.warn {
    background: color-mix(in srgb, var(--fs-misleading) 18%, transparent);
    color: var(--fs-misleading);
  }
  .hint {
    color: var(--fs-muted);
  }
  .error {
    color: var(--fs-false);
  }
  .ok {
    color: var(--fs-true);
  }
</style>
