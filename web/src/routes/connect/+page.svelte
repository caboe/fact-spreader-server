<script lang="ts">
  import { onMount } from 'svelte';
  import {
    ApiError,
    type DeviceInfo,
    createDevice,
    getSession,
    listDevices,
    revokeDevice,
  } from '$lib/api';
  import { session } from '$lib/session';
  import { t } from '$lib/i18n';

  const tr = $derived($t);
  let devices = $state<DeviceInfo[]>([]);
  let name = $state('');
  let token = $state('');
  let createdId = $state('');
  let error = $state('');
  let notice = $state('');
  let busy = $state('');
  let stateParam = $state('');
  let extensionOrigin = $state('');
  let handoffSent = $state(false);

  const canManage = $derived(Boolean($session?.user.permissions.includes('devices:manage')));

  onMount(async () => {
    const params = new URLSearchParams(window.location.search);
    stateParam = params.get('state') ?? '';
    // Only hand the token to an extension page that opened this tab (the fork's popup).
    const referrer = document.referrer;
    if (referrer && /^(chrome|moz)-extension:\/\//.test(referrer)) {
      extensionOrigin = new URL(referrer).origin;
    }
    if (!$session) {
      try {
        session.set(await getSession());
      } catch {
        session.set(null);
      }
    }
    if (!$session?.user.permissions.includes('devices:manage')) return;
    await load();
  });

  function sendToExtension(): void {
    if (!token || !stateParam || !extensionOrigin || !window.opener) return;
    window.opener.postMessage(
      { type: 'fs-device-token', state: stateParam, token },
      extensionOrigin,
    );
    handoffSent = true;
  }

  async function load(): Promise<void> {
    try {
      devices = await listDevices();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    }
  }

  async function create(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (!name.trim()) return;
    busy = 'create';
    error = '';
    notice = '';
    try {
      const result = await createDevice(name.trim());
      token = result.token;
      createdId = result.device.id;
      name = '';
      notice = tr('connect.created');
      await load();
      sendToExtension();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function revoke(device: DeviceInfo): Promise<void> {
    if (!confirm(tr('connect.revoke_confirm', { name: device.name }))) return;
    busy = device.id;
    error = '';
    try {
      await revokeDevice(device.id);
      if (device.id === createdId) {
        token = '';
        createdId = '';
      }
      notice = tr('connect.revoked');
      await load();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(token);
      notice = tr('connect.copied');
    } catch {
      notice = tr('connect.copy_failed');
    }
  }
</script>

<svelte:head><title>{tr('connect.title')} · Fact Spreader</title></svelte:head>

<h1>{tr('connect.title')}</h1>
<p class="intro">{tr('connect.intro')}</p>

{#if !canManage}
  <p class="notice" role="alert">{tr('connect.forbidden')}</p>
{:else}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if notice}<p class="ok" role="status">{notice}</p>{/if}

  {#if token}
    <section class="token" aria-live="polite">
      <h2>{tr('connect.token_title')}</h2>
      <p class="warn">{tr('connect.token_warning')}</p>
      <div class="secret">
        <code>{token}</code>
        <button type="button" onclick={copy}>{tr('connect.copy')}</button>
      </div>
      <p class="meta">{tr('connect.token_hint')}</p>
      {#if stateParam && extensionOrigin}
        {#if handoffSent}
          <p class="ok" role="status">{tr('connect.handoff_sent')}</p>
        {:else}
          <button type="button" onclick={sendToExtension}>{tr('connect.send_to_extension')}</button>
        {/if}
      {/if}
    </section>
  {/if}

  <form class="panel" onsubmit={create}>
    <h2>{tr('connect.create')}</h2>
    <label class="field">
      <span>{tr('connect.device_name')}</span>
      <input type="text" bind:value={name} placeholder="Firefox on macOS" />
    </label>
    <button type="submit" disabled={busy === 'create' || !name.trim()}>{tr('connect.create_button')}</button>
    <p class="meta">{tr('connect.permission_hint')}</p>
  </form>

  <section class="panel">
    <h2>{tr('connect.devices')}</h2>
    {#if devices.length === 0}
      <p class="muted">{tr('connect.empty')}</p>
    {/if}
    <ul class="devices">
      {#each devices as device}
        <li>
          <div>
            <strong>{device.name}</strong>
            <div class="meta">
              {(device.permissions ?? []).join(', ')} ·
              {tr('connect.created_at')}: {device.created_at}
              {#if device.last_seen_at}· {tr('connect.last_seen')}: {device.last_seen_at}{/if}
              {#if device.revoked_at}· <span class="revoked">{tr('connect.revoked_state')}</span>{/if}
            </div>
          </div>
          {#if !device.revoked_at}
            <button type="button" class="danger" onclick={() => revoke(device)} disabled={busy === device.id}>
              {tr('connect.revoke')}
            </button>
          {/if}
        </li>
      {/each}
    </ul>
  </section>

  <section class="panel">
    <h2>{tr('connect.handoff')}</h2>
    <ol class="steps">
      <li>{tr('connect.step_one')}</li>
      <li>{tr('connect.step_two')}</li>
      <li>{tr('connect.step_three')}</li>
      <li>{tr('connect.step_four')}</li>
    </ol>
    <p class="meta">{tr('connect.docs_hint')}</p>
  </section>
{/if}

<style>
  .intro {
    max-width: 60rem;
    color: var(--fs-muted);
  }
  .panel,
  .token {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1.1rem;
    margin-bottom: 1rem;
    display: grid;
    gap: 0.7rem;
    max-width: 64rem;
  }
  .panel h2,
  .token h2 {
    margin: 0;
  }
  .token {
    border-left: 4px solid var(--fs-warn, #b45309);
  }
  .warn {
    color: var(--fs-warn, #b45309);
    font-weight: 600;
    margin: 0;
  }
  .secret {
    display: flex;
    gap: 0.6rem;
    align-items: center;
    flex-wrap: wrap;
  }
  .secret code {
    background: var(--fs-bg);
    border-radius: 0.4rem;
    padding: 0.5rem 0.7rem;
    font-size: 0.9rem;
    word-break: break-all;
  }
  .field {
    display: grid;
    gap: 0.25rem;
    max-width: 28rem;
  }
  .field span {
    color: var(--fs-muted);
    font-size: 0.85rem;
  }
  .field input {
    padding: 0.5rem;
    font: inherit;
    border-radius: 0.4rem;
    border: 1px solid var(--fs-border);
    background: var(--fs-bg);
    color: var(--fs-text);
  }
  .devices {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    gap: 0.6rem;
  }
  .devices li {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    background: var(--fs-bg);
    border-radius: 0.6rem;
    padding: 0.7rem 0.9rem;
  }
  .steps {
    margin: 0;
    padding-left: 1.2rem;
    display: grid;
    gap: 0.35rem;
    font-size: 0.92rem;
  }
  button {
    font: inherit;
    padding: 0.45rem 0.95rem;
    border-radius: 0.5rem;
    border: none;
    background: var(--fs-accent);
    color: var(--fs-accent-contrast);
    font-weight: 600;
    cursor: pointer;
    justify-self: start;
  }
  button:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
  button.danger {
    background: var(--fs-false);
    color: #fff;
  }
  .meta {
    color: var(--fs-muted);
    font-size: 0.82rem;
    margin: 0;
  }
  .revoked {
    color: var(--fs-muted);
    font-style: italic;
  }
  .error {
    color: var(--fs-false);
  }
  .ok {
    color: var(--fs-true);
  }
  .notice {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1rem;
  }
</style>
