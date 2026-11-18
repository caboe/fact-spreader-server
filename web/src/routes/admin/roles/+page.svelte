<script lang="ts">
  import { onMount } from 'svelte';
  import { ApiError, assignRole, listModels, listRoles, type ModelInfo, type RoleInfo } from '$lib/api';
  import { t } from '$lib/i18n';

  const tr = $derived($t);
  let roles = $state<RoleInfo[]>([]);
  let models = $state<ModelInfo[]>([]);
  let choices = $state<Record<string, string>>({});
  let errors = $state<Record<string, string>>({});
  let notices = $state<Record<string, string>>({});
  let busy = $state('');
  let loadError = $state('');
  let showOthers = $state(false);
  let loading = $state(true);

  const baseModels = $derived(models.filter((model) => model.gateway_alias === null && model.enabled));

  onMount(load);

  function capabilityLabel(capability: string): string {
    const key = `admin.capability_${capability}`;
    const label = tr(key);
    return label === key ? capability.replaceAll('_', ' ') : label;
  }

  function formatReason(reason: string): string {
    const [code, ...rest] = reason.split(':');
    const value = rest.join(':');
    switch (code) {
      case 'not_assigned':
        return tr('admin.reason_not_assigned');
      case 'unknown_role':
        return tr('admin.reason_unknown_role', { role: value });
      case 'missing_capability':
        return tr('admin.reason_missing_capability', { capability: capabilityLabel(value) });
      case 'capability_not_tested':
        return tr('admin.reason_capability_not_tested', { capability: capabilityLabel(value) });
      case 'context_too_small':
        return tr('admin.reason_context_too_small', { context: value });
      case 'not_multilingual':
        return tr('admin.reason_not_multilingual');
      case 'embedding_dim_mismatch':
        return tr('admin.reason_embedding_dim', { dimension: value });
      default:
        return reason;
    }
  }

  // The server owns the rule (backend/app/services/capabilities.py) and still rejects an
  // unsuitable request. The UI applies it to the requirements the API returns so that the
  // selection only offers models the server would accept (PURPOSE §3.6).
  function reasonsFor(role: RoleInfo, model: ModelInfo): string[] {
    const reasons: string[] = [];
    const capabilities = model.capabilities ?? [];
    const tested = model.tested_capabilities ?? [];
    for (const capability of role.required_capabilities ?? []) {
      if (!capabilities.includes(capability)) {
        reasons.push(`missing_capability:${capability}`);
      } else if (!tested.includes(capability)) {
        reasons.push(`capability_not_tested:${capability}`);
      }
    }
    if (role.min_context && (model.context_window ?? 0) < role.min_context) {
      reasons.push(`context_too_small:${role.min_context}`);
    }
    if (role.multilingual && !model.multilingual) {
      reasons.push('not_multilingual');
    }
    if (role.embedding_dim && model.embedding_dim !== role.embedding_dim) {
      reasons.push(`embedding_dim_mismatch:${role.embedding_dim}`);
    }
    return reasons;
  }

  function isSuitable(role: RoleInfo, model: ModelInfo): boolean {
    return reasonsFor(role, model).length === 0;
  }

  function currentBase(role: RoleInfo, candidates: ModelInfo[]): ModelInfo | undefined {
    const current = role.model;
    if (!current) return undefined;
    if (current.source_model_id) {
      return candidates.find((model) => model.id === current.source_model_id);
    }
    return candidates.find(
      (model) => model.provider_id === current.provider_id && model.model_name === current.model_name,
    );
  }

  function defaultChoice(role: RoleInfo, candidates: ModelInfo[]): string {
    const current = currentBase(role, candidates);
    if (current && isSuitable(role, current)) return current.id;
    return candidates.find((model) => isSuitable(role, model))?.id ?? '';
  }

  function optionLabel(role: RoleInfo, model: ModelInfo): string {
    const reasons = reasonsFor(role, model);
    return reasons.length === 0 ? model.model_name : `${model.model_name} — ${formatReason(reasons[0]!)}`;
  }

  async function load(): Promise<void> {
    loadError = '';
    loading = true;
    try {
      const [nextRoles, nextModels] = await Promise.all([listRoles(), listModels()]);
      const base = nextModels.filter((model) => model.gateway_alias === null && model.enabled);
      roles = nextRoles;
      models = nextModels;
      for (const role of nextRoles) {
        choices[role.alias] = defaultChoice(role, base);
      }
    } catch (cause) {
      loadError = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      loading = false;
    }
  }

  async function assign(role: RoleInfo): Promise<void> {
    const modelId = choices[role.alias];
    const model = baseModels.find((candidate) => candidate.id === modelId);
    if (!model) return;
    const reasons = reasonsFor(role, model);
    if (reasons.length > 0) {
      errors[role.alias] = reasons.map(formatReason).join(' ');
      return;
    }
    busy = role.alias;
    delete errors[role.alias];
    delete notices[role.alias];
    try {
      await assignRole(role.alias, model.id);
      await load();
      notices[role.alias] = tr('admin.role_assigned');
    } catch (cause) {
      if (cause instanceof ApiError && cause.reasons.length > 0) {
        errors[role.alias] = cause.reasons.map(formatReason).join(' ');
      } else {
        errors[role.alias] = cause instanceof ApiError ? cause.message : tr('common.error');
      }
    } finally {
      busy = '';
    }
  }
</script>

<h1>{tr('admin.roles')}</h1>
<div class="toolbar">
  <p class="hint">{tr('admin.roles_hint')}</p>
  <label class="toggle">
    <input type="checkbox" bind:checked={showOthers} />
    <span>{tr('admin.show_others')}</span>
  </label>
</div>
{#if loadError}<p class="error" role="alert">{loadError}</p>{/if}
{#if loading}<p class="hint">{tr('common.loading')}</p>{/if}

<div class="roles">
  {#each roles as role (role.alias)}
    {@const available = baseModels.filter((model) => isSuitable(role, model))}
    {@const visible = showOthers ? baseModels : available}
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
        <dd>{(role.required_capabilities ?? []).map(capabilityLabel).join(', ')}</dd>
        {#if role.min_context}
          <dt>{tr('admin.min_context')}</dt>
          <dd>{role.min_context}</dd>
        {/if}
        <dt>{tr('admin.current_model')}</dt>
        <dd>{role.model ? role.model.model_name : '—'}</dd>
      </dl>
      {#if (role.reasons ?? []).length > 0}
        <div class="reasons-block">
          <p class="reasons-title">{tr('admin.current_reasons')}</p>
          <ul class="reasons">
            {#each role.reasons ?? [] as reason}
              <li>{formatReason(reason)}</li>
            {/each}
          </ul>
        </div>
      {/if}
      <div class="assign">
        <form onsubmit={(event) => (event.preventDefault(), assign(role))}>
          <label>
            <span>{tr('admin.assign_model')}</span>
            <select bind:value={choices[role.alias]} disabled={busy === role.alias}>
              {#if available.length === 0 || visible.length === 0}
                <option value="">{tr('admin.no_suitable')}</option>
              {/if}
              {#each visible as model}
                <option value={model.id} disabled={!isSuitable(role, model)}>
                  {optionLabel(role, model)}
                </option>
              {/each}
            </select>
          </label>
          <button
            type="submit"
            disabled={busy === role.alias || available.length === 0 || !choices[role.alias]}
          >
            {tr('admin.assign')}
          </button>
        </form>
        {#if available.length === 0}
          <p class="empty">
            {tr('admin.no_suitable_hint')}
            <a href="/admin/providers">{tr('admin.providers')}</a>
          </p>
        {/if}
        {#if errors[role.alias]}<p class="error" role="alert">{errors[role.alias]}</p>{/if}
        {#if notices[role.alias]}<p class="ok" role="status">{notices[role.alias]}</p>{/if}
      </div>
    </article>
  {/each}
</div>

<style>
  .toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.6rem 1rem;
    margin: 0.25rem 0 1rem;
  }
  .roles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 23rem), 1fr));
    gap: 1rem;
    align-items: stretch;
  }
  .roles > article {
    min-width: 0;
  }
  .panel {
    display: flex;
    flex-direction: column;
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1.2rem 1.3rem;
  }
  header {
    display: flex;
    gap: 0.75rem;
    align-items: flex-start;
    justify-content: space-between;
  }
  h2 {
    margin: 0;
    font-size: 1.05rem;
    line-height: 1.3;
  }
  .label {
    color: var(--fs-muted);
    margin: 0.15rem 0 0.75rem;
    font-size: 0.85rem;
  }
  dl {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.3rem 0.85rem;
    font-size: 0.85rem;
  }
  dt {
    color: var(--fs-muted);
  }
  dd {
    margin: 0;
    overflow-wrap: anywhere;
  }
  .reasons-block {
    margin-top: 0.85rem;
  }
  .reasons-title {
    margin: 0 0 0.35rem;
    color: var(--fs-muted);
    font-size: 0.78rem;
    font-weight: 600;
  }
  .reasons {
    margin: 0;
    padding-left: 1.1rem;
    color: var(--fs-misleading);
    font-size: 0.85rem;
  }
  .reasons li {
    overflow-wrap: anywhere;
  }
  .assign {
    display: grid;
    gap: 0.6rem;
    margin-top: auto;
    padding-top: 1rem;
    border-top: 1px solid color-mix(in srgb, var(--fs-border) 45%, transparent);
  }
  form {
    display: flex;
    gap: 0.55rem;
    align-items: flex-end;
    flex-wrap: wrap;
  }
  form label {
    display: grid;
    gap: 0.4rem;
    font-size: 0.8rem;
    color: var(--fs-muted);
    flex: 1 1 14rem;
    min-width: 0;
  }
  select,
  button {
    box-sizing: border-box;
    height: 2.6rem;
  }
  select {
    width: 100%;
    max-width: 100%;
    min-width: 0;
    padding: 0 0.65rem;
    border-radius: 0.5rem;
    border: 1px solid color-mix(in srgb, var(--fs-border) 60%, transparent);
    background: var(--fs-bg);
    color: var(--fs-text);
    font: inherit;
  }
  button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0 1.05rem;
    border-radius: 0.5rem;
    border: none;
    background: var(--fs-accent);
    color: var(--fs-accent-contrast);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
  }
  button:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
  .badge {
    flex: none;
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
    margin: 0;
    max-width: 62ch;
  }
  .toggle {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    color: var(--fs-muted);
    font-size: 0.85rem;
    white-space: nowrap;
    cursor: pointer;
  }
  .toggle input {
    width: 1rem;
    height: 1rem;
    accent-color: var(--fs-accent);
  }
  .empty {
    margin: 0;
    color: var(--fs-muted);
    font-size: 0.85rem;
  }
  .empty a {
    color: var(--fs-accent);
    font-weight: 600;
  }
  .error {
    margin: 0;
    color: var(--fs-false);
    font-size: 0.85rem;
  }
  .ok {
    margin: 0;
    color: var(--fs-true);
    font-size: 0.85rem;
  }
</style>
