<script lang="ts">
  import { goto } from '$app/navigation';
  import { ApiError, login } from '$lib/api';
  import { session } from '$lib/session';
  import { t } from '$lib/i18n';
  const tr = $derived($t);

  let email = $state('');
  let password = $state('');
  let totp = $state('');
  let error = $state('');
  let busy = $state(false);

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    error = '';
    busy = true;
    try {
      session.set(await login(email, password, totp));
      goto('/');
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('login.failed');
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>{tr('login.title')} · Fact Spreader</title></svelte:head>

<section class="card">
  <h1>{tr('login.title')}</h1>
  <form onsubmit={submit}>
    <label>
      <span>{tr('login.email')}</span>
      <input type="email" autocomplete="username" bind:value={email} required />
    </label>
    <label>
      <span>{tr('login.password')}</span>
      <input type="password" autocomplete="current-password" bind:value={password} required />
    </label>
    <label>
      <span>{tr('login.totp')}</span>
      <input
        type="text"
        inputmode="numeric"
        autocomplete="one-time-code"
        bind:value={totp}
        maxlength="64"
      />
    </label>
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    <button type="submit" disabled={busy}>{busy ? tr('common.loading') : tr('login.submit')}</button>
  </form>
</section>

<style>
  .card {
    max-width: 26rem;
    margin: 2rem auto;
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow);
    padding: 1.75rem;
  }
  form {
    display: grid;
    gap: 1rem;
  }
  label {
    display: grid;
    gap: 0.3rem;
    font-size: 0.9rem;
  }
  input {
    padding: 0.55rem 0.7rem;
    border-radius: 0.5rem;
    border: 1px solid color-mix(in srgb, var(--fs-border) 60%, transparent);
    background: var(--fs-bg);
    color: var(--fs-text);
    font: inherit;
  }
  button {
    padding: 0.6rem 1rem;
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
  .error {
    color: var(--fs-false);
    margin: 0;
  }
</style>
