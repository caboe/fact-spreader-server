<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { afterNavigate, goto } from '$app/navigation';
  import { dev } from '$app/environment';
  import { page } from '$app/stores';
  import { getSession, logout } from '$lib/api';
  import { session } from '$lib/session';
  import { LANG_LABELS, LANGS, initialLang, lang, setLang, t, type Lang } from '$lib/i18n';
  import { applyTheme, initialTheme, type Theme } from '$lib/theme';
  import '../app.css';
  const tr = $derived($t);

  let { children } = $props();

  interface InstallPrompt extends Event {
    prompt: () => Promise<void>;
    userChoice: Promise<{ outcome: string }>;
  }

  let theme = $state<Theme>('auto');
  let menuOpen = $state(false);
  let accountEl = $state<HTMLDivElement | null>(null);
  let accountButton = $state<HTMLButtonElement | null>(null);
  let installPrompt = $state<InstallPrompt | null>(null);
  let iosHint = $state(false);
  let installDismissed = $state(false);
  let removePromptListener: (() => void) | null = null;

  // A disclosure menu must not survive a route change or a click elsewhere.
  afterNavigate(() => {
    menuOpen = false;
  });

  function closeOnOutside(event: PointerEvent): void {
    if (!menuOpen) return;
    const target = event.target;
    if (target instanceof Node && accountEl && !accountEl.contains(target)) menuOpen = false;
  }

  function closeOnEscape(event: KeyboardEvent): void {
    if (event.key !== 'Escape' || !menuOpen) return;
    menuOpen = false;
    accountButton?.focus();
  }

  onMount(() => {
    document.addEventListener('pointerdown', closeOnOutside);
    document.addEventListener('keydown', closeOnEscape);
  });

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

  onDestroy(() => {
    document.removeEventListener('pointerdown', closeOnOutside);
    document.removeEventListener('keydown', closeOnEscape);
    removePromptListener?.();
  });

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
    menuOpen = false;
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

{#snippet userIcon()}
  <svg
    viewBox="0 0 24 24"
    width="18"
    height="18"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <circle cx="12" cy="8" r="3.4"></circle>
    <path d="M5.2 19.5c.8-3.6 3.2-5.5 6.8-5.5s6 1.9 6.8 5.5"></path>
  </svg>
{/snippet}

<header class="shell-header">
  <a class="brand" href="/">Fact Spreader</a>
  <nav aria-label="Main">
    <a href="/" aria-current={$page?.url?.pathname === '/' ? 'page' : undefined}>{tr('nav.check')}</a>
    <a href="/archive">{tr('nav.archive')}</a>
    <a href="/chat">{tr('nav.chat')}</a>
    {#if $session?.user.permissions.includes('search:use')}
      <a
        href="/retrieval"
        aria-current={$page?.url?.pathname.startsWith('/retrieval') ? 'page' : undefined}
        >{tr('nav.retrieval')}</a
      >
    {/if}
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
  <div class="account" bind:this={accountEl}>
    {#if $session}
      <button
        type="button"
        class="account-trigger"
        bind:this={accountButton}
        aria-expanded={menuOpen}
        aria-controls="account-menu"
        onclick={() => (menuOpen = !menuOpen)}
      >
        <span class="avatar">{@render userIcon()}</span>
        <span class="account-name">{$session.user.display_name}</span>
        <svg
          class="chevron"
          class:open={menuOpen}
          viewBox="0 0 16 16"
          width="12"
          height="12"
          aria-hidden="true"
          focusable="false"
        >
          <path
            d="M3 6l5 5 5-5"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
          ></path>
        </svg>
      </button>
      {#if menuOpen}
        <div
          class="account-menu"
          id="account-menu"
          role="group"
          aria-label={tr('nav.settings')}
        >
          <div class="identity">
            <span class="avatar avatar-large">{@render userIcon()}</span>
            <span class="identity-text">
              <strong>{$session.user.display_name}</strong>
              <span>{$session.user.email}</span>
            </span>
          </div>
          <label class="menu-field">
            <span class="menu-label">{tr('nav.language')}</span>
            <select value={$lang} onchange={chooseLanguage}>
              {#each LANGS as code}
                <option value={code}>{LANG_LABELS[code]}</option>
              {/each}
            </select>
          </label>
          <div class="menu-field">
            <span class="menu-label">{tr('theme.label')}</span>
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
          </div>
          <button type="button" class="menu-action" onclick={signOut}>{tr('nav.logout')}</button>
        </div>
      {/if}
    {:else}
      <a class="account-trigger" href="/login">
        <span class="avatar">{@render userIcon()}</span>
        <span class="account-name">{tr('nav.login')}</span>
      </a>
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
    flex-wrap: wrap;
    gap: 0.35rem 1rem;
    min-width: 0;
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
    min-width: 0;
    font-size: 0.9rem;
  }
  .account-trigger {
    display: inline-flex;
    gap: 0.55rem;
    align-items: center;
    max-width: 16rem;
    padding: 0.25rem 0.55rem 0.25rem 0.3rem;
    border: 1px solid var(--fs-border);
    border-radius: 999px;
    background: var(--fs-surface);
    color: var(--fs-text);
    font: inherit;
    font-weight: 600;
    text-decoration: none;
    cursor: pointer;
  }
  .account-trigger:hover {
    background: var(--fs-bg);
  }
  .account-trigger:focus-visible {
    outline: 2px solid var(--fs-accent);
    outline-offset: 2px;
  }
  .avatar {
    display: grid;
    place-items: center;
    flex: none;
    width: 1.8rem;
    height: 1.8rem;
    border-radius: 50%;
    background: var(--fs-accent-soft);
    color: var(--fs-accent);
  }
  .avatar-large {
    width: 2.15rem;
    height: 2.15rem;
  }
  .account-name {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .chevron {
    flex: none;
    color: var(--fs-muted);
    transition: transform 0.15s ease;
  }
  .chevron.open {
    transform: rotate(180deg);
  }
  .account-menu {
    position: absolute;
    top: calc(100% + 0.4rem);
    right: 1.25rem;
    z-index: 20;
    display: grid;
    gap: 0.85rem;
    width: min(19rem, calc(100vw - 2.5rem));
    max-height: calc(100vh - 5rem);
    overflow-y: auto;
    padding: 0.9rem;
    border: 1px solid var(--fs-border);
    border-radius: 0.8rem;
    background: var(--fs-surface);
    color: var(--fs-text);
    box-shadow: var(--fs-shadow);
    text-align: left;
  }
  .identity {
    display: flex;
    gap: 0.65rem;
    align-items: center;
    min-width: 0;
  }
  .identity-text {
    display: grid;
    min-width: 0;
    line-height: 1.35;
  }
  .identity-text strong,
  .identity-text span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .identity-text span {
    color: var(--fs-muted);
    font-size: 0.78rem;
    font-weight: 400;
  }
  .menu-field {
    display: grid;
    gap: 0.3rem;
  }
  .menu-label {
    color: var(--fs-muted);
    font-size: 0.78rem;
    font-weight: 600;
  }
  .account-menu select {
    width: 100%;
    padding: 0.42rem 0.5rem;
    border: 1px solid var(--fs-border);
    border-radius: 0.45rem;
    background: var(--fs-bg);
    color: var(--fs-text);
    font: inherit;
    font-size: 0.88rem;
  }
  .theme-switch {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.15rem;
    padding: 0.15rem;
    border: 1px solid var(--fs-border);
    border-radius: 0.5rem;
    background: var(--fs-bg);
  }
  .theme-switch button {
    min-width: 0;
    padding: 0.32rem 0.2rem;
    border: none;
    border-radius: 0.35rem;
    background: none;
    color: var(--fs-muted);
    font: inherit;
    font-size: 0.78rem;
    cursor: pointer;
  }
  .theme-switch button[aria-pressed='true'] {
    background: var(--fs-accent-soft);
    color: var(--fs-accent);
    font-weight: 700;
  }
  .theme-switch button:focus-visible,
  .menu-action:focus-visible {
    outline: 2px solid var(--fs-accent);
    outline-offset: 1px;
  }
  .menu-action {
    margin-top: 0.1rem;
    padding: 0.75rem 0 0;
    border: none;
    border-top: 1px solid var(--fs-border);
    background: none;
    color: var(--fs-accent);
    font: inherit;
    font-weight: 600;
    text-align: left;
    cursor: pointer;
  }
  .menu-action:hover {
    text-decoration: underline;
  }
  @media (max-width: 720px) {
    .shell-header {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 0.6rem 1rem;
    }
    .brand {
      grid-column: 1;
      grid-row: 1;
    }
    .account {
      grid-column: 2;
      grid-row: 1;
      margin-left: 0;
    }
    nav {
      grid-column: 1 / -1;
      grid-row: 2;
    }
    .account-trigger {
      max-width: 11rem;
    }
    .account-menu {
      right: 0.75rem;
      width: min(19rem, calc(100vw - 1.5rem));
    }
  }
  .link {
    background: none;
    border: none;
    color: var(--fs-accent);
    cursor: pointer;
    font: inherit;
    padding: 0;
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
