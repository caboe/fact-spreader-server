<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { ApiError, confirmTotp, getSession, startTotpSetup } from '$lib/api';
  import { session } from '$lib/session';
  import { t } from '$lib/i18n';

  const tr = $derived($t);
  let secret = $state('');
  let uri = $state('');
  let code = $state('');
  let recoveryCodes = $state<string[]>([]);
  let error = $state('');
  let busy = $state(false);

  onMount(async () => {
    try {
      const current = await getSession();
      session.set(current);
      if (!current) await goto('/login');
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    }
  });

  async function begin(): Promise<void> {
    error = '';
    busy = true;
    try {
      const setup = await startTotpSetup();
      secret = setup.secret;
      uri = setup.otpauth_uri;
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = false;
    }
  }

  async function confirm(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    error = '';
    busy = true;
    try {
      const result = await confirmTotp(code.trim());
      recoveryCodes = result.recovery_codes;
      session.update((current) =>
        current ? { ...current, totp_setup_required: false } : current,
      );
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>{tr('totp.title')} · Fact Spreader</title></svelte:head>

<section class="card">
  <h1>{tr('totp.title')}</h1>

  {#if recoveryCodes.length > 0}
    <p>{tr('totp.enabled')}</p>
    <h2>{tr('totp.recovery')}</h2>
    <ul class="codes">
      {#each recoveryCodes as recovery}
        <li><code>{recovery}</code></li>
      {/each}
    </ul>
    <a class="button" href="/">{tr('totp.done')}</a>
  {:else if secret}
    <dl>
        <dt>{tr('totp.secret')}</dt>
        <dd><code class="secret">{secret}</code></dd>
        <dt>{tr('totp.uri')}</dt>
        <dd><code class="uri">{uri}</code></dd>
      </dl>
      <form onsubmit={confirm}>
        <label>
          <span>{tr('totp.code')}</span>
          <input
            type="text"
            inputmode="numeric"
            autocomplete="one-time-code"
            bind:value={code}
            required
          />
        </label>
        <button class="button" type="submit" disabled={busy}>
          {tr('totp.confirm')}
        </button>
      </form>
  {:else if $session && !$session.totp_setup_required}
    <p class="status">{tr('totp.enabled')}</p>
    <p class="hint">{tr('totp.re_enrol_hint')}</p>
    <div class="actions">
      <button class="button" type="button" onclick={begin} disabled={busy}>
        {tr('totp.re_enrol')}
      </button>
      <a class="button secondary" href="/">{tr('totp.done')}</a>
    </div>
  {:else}
    <p>{tr('totp.intro')}</p>
    <div class="actions">
      <button class="button" type="button" onclick={begin} disabled={busy}>
        {tr('totp.start')}
      </button>
    </div>
  {/if}

  {#if error}<p class="error" role="alert">{error}</p>{/if}
</section>

<style>
  .card {
    max-width: 38rem;
    margin: 3rem auto;
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow);
    padding: 2.5rem;
    display: grid;
    gap: 1.25rem;
  }
  .card h1 {
    margin: 0;
    font-size: 1.6rem;
  }
  .card p {
    margin: 0;
    line-height: 1.6;
  }
  .status {
    font-weight: 600;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.8rem;
    margin-top: 0.4rem;
  }
  @media (max-width: 520px) {
    .card {
      margin: 1.5rem auto;
      padding: 1.5rem;
    }
    .actions .button {
      width: 100%;
      text-align: center;
    }
  }
  dl {
    display: grid;
    gap: 0.35rem;
    margin: 1rem 0 1.5rem;
  }
  dt {
    color: var(--fs-muted);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  dd {
    margin: 0 0 0.75rem;
  }
  code {
    word-break: break-all;
    font-size: 0.95rem;
  }
  .secret {
    font-size: 1.15rem;
    letter-spacing: 0.08em;
  }
  form {
    display: grid;
    gap: 1rem;
    max-width: 20rem;
  }
  label {
    display: grid;
    gap: 0.3rem;
    font-size: 0.9rem;
  }
  input {
    padding: 0.65rem 0.8rem;
    border-radius: 0.6rem;
    border: 1px solid color-mix(in srgb, var(--fs-border) 60%, transparent);
    background: var(--fs-bg);
    color: var(--fs-text);
    font: inherit;
  }
  .button {
    display: inline-block;
    padding: 0.7rem 1.35rem;
    border-radius: 0.6rem;
    border: none;
    background: var(--fs-accent);
    color: var(--fs-accent-contrast);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
    text-decoration: none;
  }
  .button:disabled {
    opacity: 0.6;
    cursor: wait;
  }
  .codes {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr));
    gap: 0.5rem;
    padding: 0;
    list-style: none;
  }
  .codes li {
    background: var(--fs-bg);
    border-radius: 0.5rem;
    padding: 0.5rem 0.7rem;
  }
  .error {
    color: var(--fs-false);
  }
  .hint {
    color: var(--fs-muted);
    font-size: 0.9rem;
    line-height: 1.55;
  }
  .button.secondary {
    background: var(--fs-accent-soft);
    color: var(--fs-accent);
  }
</style>
