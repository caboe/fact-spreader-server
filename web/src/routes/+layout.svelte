<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { dev } from '$app/environment';
  import { page } from '$app/stores';
  import { getSession, logout } from '$lib/api';
  import { session } from '$lib/session';
  import { LANGS, initialLang, lang, setLang, t, type Lang } from '$lib/i18n';
  import { applyTheme, initialTheme, type Theme } from '$lib/theme';
  import '../app.css';
  const tr = $derived($t);

  let { children } = $props();

  interface InstallPrompt extends Event {
    prompt: () => Promise<void>;
    userChoice: Promise<{ outcome: string }>;
  }

  let theme = $state<Theme>('auto');
  let installPrompt = $state<InstallPrompt | null>(null);
  let iosHint = $state(false);
  let installDismissed = $state(false);
  let removePromptListener: (() => void) | null = null;

  onMount(async () => {
    if (!dev && 'serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js').catch(() => {
        /* installability is a progressive enhancement */
      });
    }
    const capture = (event: Event) => {
      event.preventDefault();
      installPrompt = event as InstallPrompt;
    };
    window.addEventListener('beforeinstallprompt', capture);
    removePromptListener = () => window.removeEventListener('beforeinstallprompt', capture);
    const standalone =
      window.matchMedia('(display-mode: standalone)').matches ||
      (navigator as { standalone?: boolean }).standalone === true;
    const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
    installDismissed = localStorage.getItem('fs-pwa-dismissed') === '1';
    iosHint = ios && !standalone;

    setLang(initialLang());
    theme = initialTheme();
    applyTheme(theme);
    try {
      session.set(await getSession());
    } catch {
      session.set(null);
    }
  });

  onDestroy(() => removePromptListener?.());

  async function install(): Promise<void> {
    if (!installPrompt) return;
    await installPrompt.prompt();
    await installPrompt.userChoice;
    installPrompt = null;
  }

  function dismissInstall(): void {
    installDismissed = true;
    localStorage.setItem('fs-pwa-dismissed', '1');
  }

  async function signOut(): Promise<void> {
    try {
      await logout();
    } finally {
      session.set(null);
      goto('/login');
    }
  }

  function chooseTheme(next: Theme): void {
    theme = next;
    applyTheme(next);
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
    {#if $session?.user.permissions.includes('devices:manage')}
      <a href="/connect" aria-current={$page?.url?.pathname.startsWith('/connect') ? 'page' : undefined}
        >{tr('nav.connect')}</a
      >
    {/if}
    {#if $session?.user.permissions.includes('documents:submit')}
      <a href="/submit" aria-current={$page?.url?.pathname.startsWith('/submit') ? 'page' : undefined}
        >{tr('nav.submit')}</a
      >
    {/if}
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
    <div class="theme-switch" role="group" aria-label={tr('theme.label')}>
      {#each [['auto', tr('theme.auto')], ['light', tr('theme.light')], ['dark', tr('theme.dark')]] as [value, label]}
        <button
          type="button"
          aria-pressed={theme === value}
          onclick={() => chooseTheme(value as Theme)}
        >
          {label}
        </button>
      {/each}
    </div>
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

{#if !installDismissed && (installPrompt || iosHint)}
  <div class="install-banner" role="status">
    <span>{installPrompt ? tr('pwa.install_hint') : tr('pwa.ios_hint')}</span>
    {#if installPrompt}
      <button type="button" onclick={install}>{tr('pwa.install')}</button>
    {/if}
    <button type="button" class="link" onclick={dismissInstall}>{tr('pwa.dismiss')}</button>
  </div>
{/if}

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
  .install-banner {
    display: flex;
    gap: 0.7rem;
    align-items: center;
    flex-wrap: wrap;
    padding: 0.5rem 1.2rem;
    background: var(--fs-accent-soft);
    color: var(--fs-text);
    font-size: 0.88rem;
  }
  .install-banner button {
    padding: 0.3rem 0.8rem;
    border-radius: 0.4rem;
    border: none;
    background: var(--fs-accent);
    color: var(--fs-accent-contrast);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }
  .install-banner button.link {
    background: none;
    color: var(--fs-accent);
    font-weight: 500;
  }
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
  .theme-switch {
    display: flex;
    gap: 0.1rem;
    padding: 0.15rem;
    border-radius: 999px;
    background: var(--fs-bg);
  }
  .theme-switch button {
    border: none;
    background: none;
    color: var(--fs-muted);
    font: inherit;
    font-size: 0.76rem;
    padding: 0.22rem 0.5rem;
    border-radius: 999px;
    cursor: pointer;
  }
  .theme-switch button[aria-pressed='true'] {
    background: var(--fs-accent-soft);
    color: var(--fs-accent);
    font-weight: 700;
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
