<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { getSession, logout } from '$lib/api';
  import { session } from '$lib/session';
  import { LANGS, initialLang, lang, setLang, t, type Lang } from '$lib/i18n';
  import '../app.css';
  const tr = $derived($t);

  let { children } = $props();

  onMount(async () => {
    setLang(initialLang());
    try {
      session.set(await getSession());
    } catch {
      session.set(null);
    }
  });

  async function signOut(): Promise<void> {
    try {
      await logout();
    } finally {
      session.set(null);
      goto('/login');
    }
  }

  function chooseLanguage(event: Event): void {
    const value = (event.currentTarget as HTMLSelectElement).value as Lang;
    setLang(value);
  }
</script>

<svelte:head>
  <title>Fact Spreader</title>
</svelte:head>

<header class="shell-header">
  <a class="brand" href="/">Fact Spreader</a>
  <nav aria-label="Main">
    <a href="/" aria-current={$page?.url?.pathname === '/' ? 'page' : undefined}>{tr('nav.check')}</a>
    <a href="/archive">{tr('nav.archive')}</a>
    <a href="/chat">{tr('nav.chat')}</a>
    {#if $session?.user.permissions.includes('documents:review')}
      <a href="/editorial" aria-current={$page?.url?.pathname.startsWith('/editorial') ? 'page' : undefined}
        >{tr('nav.editorial')}</a
      >
    {/if}
    {#if $session?.user.permissions.some((permission) => ['config:manage', 'users:manage'].includes(permission))}
      <a href="/admin">{tr('nav.admin')}</a>
    {/if}
  </nav>
  <div class="account">
    <label class="language">
      <span>{tr('nav.language')}</span>
      <select value={$lang} onchange={chooseLanguage}>
        {#each LANGS as code}
          <option value={code}>{code}</option>
        {/each}
      </select>
    </label>
    {#if $session}
      <span class="who">{$session.user.display_name}</span>
      <button type="button" class="link" onclick={signOut}>{tr('nav.logout')}</button>
    {:else}
      <a href="/login">{tr('nav.login')}</a>
    {/if}
  </div>
</header>

{#if $session?.totp_setup_required}
  <div class="setup-banner" role="status">
    <span>{tr('totp.banner')}</span>
    <a href="/totp">{tr('totp.enable')}</a>
  </div>
{/if}

<main class="shell-main">
  {@render children()}
</main>

<style>
  .shell-header {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem 1.5rem;
    align-items: center;
    padding: 0.6rem 1.25rem;
    background: var(--fs-surface);
    box-shadow: var(--fs-shadow-soft);
    position: sticky;
    top: 0;
    z-index: 10;
  }
  .brand {
    font-weight: 700;
    text-decoration: none;
    color: var(--fs-text);
    font-size: 1.05rem;
  }
  nav {
    display: flex;
    gap: 1rem;
  }
  nav a {
    text-decoration: none;
  }
  nav a[aria-current='page'] {
    font-weight: 700;
    text-decoration: underline;
  }
  .account {
    margin-left: auto;
    display: flex;
    gap: 0.75rem;
    align-items: center;
    font-size: 0.9rem;
  }
  .language {
    display: flex;
    gap: 0.35rem;
    align-items: center;
    color: var(--fs-muted);
  }
  select {
    background: var(--fs-bg);
    color: var(--fs-text);
    border: 1px solid var(--fs-border);
    border-radius: 0.4rem;
    padding: 0.15rem 0.3rem;
  }
  .link {
    background: none;
    border: none;
    color: var(--fs-accent);
    cursor: pointer;
    font: inherit;
    padding: 0;
  }
  .who {
    color: var(--fs-muted);
  }
  .setup-banner {
    display: flex;
    gap: 0.75rem;
    flex-wrap: wrap;
    justify-content: center;
    align-items: center;
    padding: 0.55rem 1rem;
    background: var(--fs-accent-soft);
    color: var(--fs-text);
    font-size: 0.9rem;
  }
  .shell-main {
    padding: 1.5rem 1.25rem 3rem;
    max-width: 72rem;
    margin: 0 auto;
  }
</style>
