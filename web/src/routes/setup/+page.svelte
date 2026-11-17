<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import {
    ApiError,
    setupAdmin,
    setupComplete,
    setupConfirmTotp,
    setupModerationTest,
    setupModels,
    setupOrganization,
    setupProvider,
    setupStatus,
    type SetupAdminCreated,
    type SetupStatus,
  } from '$lib/api';
  import { session } from '$lib/session';
  import { t } from '$lib/i18n';

  const tr = $derived($t);

  let status = $state<SetupStatus | null>(null);
  let admin = $state<SetupAdminCreated | null>(null);
  let recoveryCodes = $state<string[]>([]);
  let providerModels = $state<string[]>([]);
  let moderation = $state<{ backend: string; flagged: boolean; categories: string[] } | null>(null);
  let error = $state('');
  let notice = $state('');
  let busy = $state('');

  let token = $state('');
  let email = $state('');
  let password = $state('');
  let displayName = $state('');
  let code = $state('');
  let name = $state('Fact Spreader');
  let organization = $state('');
  let contact = $state('');
  let overviewPublic = $state(false);
  let budget = $state<number | undefined>(undefined);
  let providerName = $state('deepseek');
  let baseUrl = $state('https://api.deepseek.com/v1');
  let apiKey = $state('');
  let isLocal = $state(false);
  let providerUse = $state<'chat' | 'embedding'>('chat');
  let chatModel = $state('');
  let embeddingModel = $state('');
  let embeddingDim = $state<number | undefined>(undefined);
  let multilingual = $state(true);

  onMount(load);

  async function load(): Promise<void> {
    error = '';
    try {
      status = await setupStatus();
      try {
        session.set(await (await fetch('/api/auth/session', { credentials: 'include' })).json());
      } catch {
        session.set(null);
      }
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    }
  }

  function stepDone(step: string): boolean {
    return status?.steps?.[step] === true;
  }

  async function createAdmin(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    busy = 'admin';
    error = '';
    try {
      admin = await setupAdmin({
        token,
        email,
        password,
        display_name: displayName,
      });
      notice = tr('setup.admin_created');
      await load();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function confirmTotp(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    busy = 'totp';
    error = '';
    try {
      const result = await setupConfirmTotp(token, code);
      recoveryCodes = result.recovery_codes;
      notice = tr('setup.totp_confirmed');
      code = '';
      await load();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function saveOrganization(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    busy = 'organization';
    error = '';
    try {
      status = await setupOrganization({
        name,
        organization: organization || undefined,
        contact: contact || undefined,
        overview_public: overviewPublic,
        monthly_budget_usd: budget,
      });
      notice = tr('setup.organization_saved');
      await load();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function testProvider(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    busy = 'provider';
    error = '';
    try {
      const result = await setupProvider({
        name: providerName,
        base_url: baseUrl,
        api_key: apiKey || undefined,
        is_local: isLocal,
        use: providerUse,
      });
      providerModels = result.models;
      notice = tr('setup.provider_ok', { count: result.models.length });
      apiKey = '';
      await load();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function assignModels(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    busy = 'models';
    error = '';
    try {
      await setupModels({
        chat_model: chatModel || providerModels[0] || '',
        embedding_model: embeddingModel || providerModels[0] || '',
        embedding_dim: embeddingDim,
        multilingual,
      });
      notice = tr('setup.models_saved');
      await load();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function runModeration(): Promise<void> {
    busy = 'moderation';
    error = '';
    try {
      moderation = await setupModerationTest();
      notice = moderation.flagged ? tr('setup.moderation_failed') : tr('setup.moderation_ok');
      await load();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function finish(): Promise<void> {
    busy = 'complete';
    error = '';
    try {
      await setupComplete();
      notice = tr('setup.complete');
      await load();
      await goto('/');
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }
</script>

<svelte:head><title>{tr('setup.title')} · Fact Spreader</title></svelte:head>

<h1>{tr('setup.title')}</h1>
<p class="intro">{tr('setup.intro')}</p>

{#if error}<p class="error" role="alert">{error}</p>{/if}
{#if notice}<p class="ok" role="status">{notice}</p>{/if}

{#if status?.complete}
  <section class="panel">
    <p>{tr('setup.already_complete')}</p>
    <a href="/">{tr('setup.open_app')}</a>
  </section>
{:else if status}
  <ol class="steps" aria-label={tr('setup.progress')}>
    {#each ['admin', 'totp', 'organization', 'provider', 'models', 'moderation'] as step}
      <li class:done={stepDone(step)} aria-current={status.next_step === step ? 'step' : undefined}>
        <span>{tr(`setup.step_${step}`)}</span>
        <span class="mark">{stepDone(step) ? '✓' : '·'}</span>
      </li>
    {/each}
  </ol>

  {#if !stepDone('admin')}
    <section class="panel">
      <h2>{tr('setup.step_admin')}</h2>
      <form onsubmit={createAdmin}>
        <label class="field"><span>{tr('setup.token')}</span><input type="password" bind:value={token} required /></label>
        <label class="field"><span>{tr('login.email')}</span><input type="email" bind:value={email} required /></label>
        <label class="field"><span>{tr('login.password')}</span><input type="password" bind:value={password} required /></label>
        <label class="field"><span>{tr('setup.display_name')}</span><input type="text" bind:value={displayName} required /></label>
        <button type="submit" disabled={busy === 'admin'}>{tr('setup.create_admin')}</button>
      </form>
    </section>
  {:else if !stepDone('totp')}
    <section class="panel">
      <h2>{tr('setup.step_totp')}</h2>
      {#if admin}
        <p class="meta">{tr('setup.totp_hint')}</p>
        <p class="mono secret">{admin.totp_secret}</p>
        <p class="meta mono">{admin.provisioning_uri}</p>
      {:else}
        <p class="meta">{tr('setup.totp_after_reload')}</p>
      {/if}
      <form onsubmit={confirmTotp}>
        <label class="field"><span>{tr('setup.totp_code')}</span><input type="text" inputmode="numeric" bind:value={code} required /></label>
        <button type="submit" disabled={busy === 'totp' || !token || !code}>{tr('setup.confirm_totp')}</button>
      </form>
    </section>
  {:else if recoveryCodes.length > 0}
    <section class="panel">
      <h2>{tr('setup.recovery')}</h2>
      <p class="warn">{tr('setup.recovery_warning')}</p>
      <ul class="codes">{#each recoveryCodes as recoveryCode}<li class="mono">{recoveryCode}</li>{/each}</ul>
      <a href="/login">{tr('setup.sign_in')}</a>
    </section>
  {:else if !stepDone('organization')}
    <section class="panel">
      <h2>{tr('setup.step_organization')}</h2>
      <form onsubmit={saveOrganization}>
        <label class="field"><span>{tr('setup.instance_name')}</span><input type="text" bind:value={name} required /></label>
        <label class="field"><span>{tr('setup.organization')}</span><input type="text" bind:value={organization} /></label>
        <label class="field"><span>{tr('setup.contact')}</span><input type="text" bind:value={contact} /></label>
        <label class="check"><input type="checkbox" bind:checked={overviewPublic} /><span>{tr('setup.overview_public')}</span></label>
        <label class="field"><span>{tr('setup.monthly_budget')}</span><input type="number" min="1" step="0.01" bind:value={budget} /></label>
        <button type="submit" disabled={busy === 'organization'}>{tr('common.save')}</button>
      </form>
    </section>
  {:else if !stepDone('provider')}
    <section class="panel">
      <h2>{tr('setup.step_provider')}</h2>
      <form onsubmit={testProvider}>
        <label class="field"><span>{tr('setup.provider_name')}</span><input type="text" bind:value={providerName} required /></label>
        <label class="field"><span>{tr('setup.base_url')}</span><input type="url" bind:value={baseUrl} required /></label>
        <label class="field"><span>{tr('setup.api_key')}</span><input type="password" bind:value={apiKey} /></label>
        <label class="check"><input type="checkbox" bind:checked={isLocal} /><span>{tr('setup.local_provider')}</span></label>
        <label class="field"><span>{tr('setup.provider_use')}</span>
          <select bind:value={providerUse}><option value="chat">chat</option><option value="embedding">embedding</option></select>
        </label>
        <button type="submit" disabled={busy === 'provider'}>{tr('setup.test_provider')}</button>
      </form>
      {#if providerModels.length > 0}
        <p class="meta">{tr('setup.models_found')}: {providerModels.slice(0, 8).join(', ')}{#if providerModels.length > 8}…{/if}</p>
      {/if}
    </section>
  {:else if !stepDone('models')}
    <section class="panel">
      <h2>{tr('setup.step_models')}</h2>
      <form onsubmit={assignModels}>
        <label class="field"><span>{tr('setup.chat_model')}</span><input type="text" bind:value={chatModel} required /></label>
        <label class="field"><span>{tr('setup.embedding_model')}</span><input type="text" bind:value={embeddingModel} required /></label>
        <label class="field"><span>{tr('setup.embedding_dim')}</span><input type="number" min="1" max="8192" bind:value={embeddingDim} /></label>
        <label class="check"><input type="checkbox" bind:checked={multilingual} /><span>{tr('setup.multilingual')}</span></label>
        <button type="submit" disabled={busy === 'models'}>{tr('common.save')}</button>
      </form>
    </section>
  {:else if !stepDone('moderation')}
    <section class="panel">
      <h2>{tr('setup.step_moderation')}</h2>
      <p class="meta">{tr('setup.moderation_hint')}</p>
      <div class="row">
        <button type="button" onclick={runModeration} disabled={busy === 'moderation'}>{tr('setup.run_moderation')}</button>
        {#if moderation}
          <span class="badge" class:pass={!moderation.flagged} class:fail={moderation.flagged}>
            {moderation.flagged ? tr('setup.moderation_failed') : tr('setup.moderation_ok')}
          </span>
        {/if}
      </div>
    </section>
  {:else}
    <section class="panel">
      <h2>{tr('setup.finish')}</h2>
      <p class="meta">{tr('setup.all_steps_done')}</p>
      <button type="button" onclick={finish} disabled={busy === 'complete'}>{tr('setup.finish')}</button>
    </section>
  {/if}
{/if}

<style>
  .intro {
    max-width: 60rem;
    color: var(--fs-muted);
  }
  .steps {
    list-style: none;
    padding: 0;
    margin: 1rem 0;
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
  }
  .steps li {
    display: flex;
    gap: 0.4rem;
    align-items: center;
    padding: 0.35rem 0.7rem;
    border-radius: 999px;
    background: var(--fs-surface);
    box-shadow: var(--fs-shadow-soft);
    font-size: 0.85rem;
  }
  .steps li[aria-current='step'] {
    background: var(--fs-accent-soft);
    color: var(--fs-accent);
    font-weight: 700;
  }
  .steps li.done .mark {
    color: var(--fs-true);
  }
  .panel {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1.2rem;
    display: grid;
    gap: 0.8rem;
    max-width: 44rem;
  }
  .panel h2 {
    margin: 0;
  }
  form {
    display: grid;
    gap: 0.7rem;
  }
  .field {
    display: grid;
    gap: 0.25rem;
    font-size: 0.9rem;
  }
  .field span {
    color: var(--fs-muted);
  }
  .field input,
  .field select {
    padding: 0.5rem;
    font: inherit;
    border-radius: 0.4rem;
    border: 1px solid var(--fs-border);
    background: var(--fs-bg);
    color: var(--fs-text);
  }
  .check {
    display: flex;
    gap: 0.4rem;
    align-items: center;
    font-size: 0.88rem;
  }
  button {
    justify-self: start;
    font: inherit;
    padding: 0.45rem 0.95rem;
    border-radius: 0.5rem;
    border: none;
    background: var(--fs-accent);
    color: var(--fs-accent-contrast);
    font-weight: 600;
    cursor: pointer;
  }
  button:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
  .row {
    display: flex;
    gap: 0.6rem;
    align-items: center;
    flex-wrap: wrap;
  }
  .meta {
    color: var(--fs-muted);
    font-size: 0.82rem;
    margin: 0;
  }
  .mono {
    font-family: var(--fs-mono, ui-monospace, monospace);
  }
  .secret {
    background: var(--fs-bg);
    padding: 0.5rem 0.7rem;
    border-radius: 0.4rem;
    word-break: break-all;
  }
  .codes {
    list-style: none;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
    gap: 0.3rem;
  }
  .codes li {
    background: var(--fs-bg);
    padding: 0.3rem 0.5rem;
    border-radius: 0.35rem;
  }
  .warn {
    color: var(--fs-warn, #b45309);
    font-weight: 600;
    margin: 0;
  }
  .badge {
    padding: 0.2rem 0.6rem;
    border-radius: 999px;
    background: var(--fs-bg);
    font-size: 0.82rem;
  }
  .badge.pass {
    color: var(--fs-true);
  }
  .badge.fail {
    color: var(--fs-false);
  }
  .error {
    color: var(--fs-false);
  }
  .ok {
    color: var(--fs-true);
  }
</style>
