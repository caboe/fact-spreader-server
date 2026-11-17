<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { getSession } from '$lib/api';
  import { session } from '$lib/session';
  import { t } from '$lib/i18n';

  const tr = $derived($t);
  let { children } = $props();
  const canAdmin = $derived(
    Boolean(
      $session?.user.permissions.some((permission) =>
        ['config:manage', 'users:manage', 'usage:read'].includes(permission),
      ),
    ),
  );

  onMount(async () => {
    if (!$session) {
      try {
        session.set(await getSession());
      } catch {
        session.set(null);
      }
    }
    if (!$session) await goto('/login');
  });
</script>

<svelte:head><title>Admin · Fact Spreader</title></svelte:head>

<div class="admin">
  <nav class="tabs" aria-label="Admin">
    <a href="/admin" aria-current={$page.url.pathname === '/admin' ? 'page' : undefined}
      >{tr('admin.overview')}</a
    >
    <a href="/admin/providers" aria-current={$page.url.pathname === '/admin/providers' ? 'page' : undefined}
      >{tr('admin.providers')}</a
    >
    <a href="/admin/roles" aria-current={$page.url.pathname === '/admin/roles' ? 'page' : undefined}
      >{tr('admin.roles')}</a
    >
    <a href="/admin/users" aria-current={$page.url.pathname === '/admin/users' ? 'page' : undefined}
      >{tr('admin.users')}</a
    >
    <a href="/admin/usage" aria-current={$page.url.pathname === '/admin/usage' ? 'page' : undefined}
      >{tr('admin.usage')}</a
    >
    <a href="/admin/settings" aria-current={$page.url.pathname === '/admin/settings' ? 'page' : undefined}
      >{tr('admin.settings')}</a
    >
    <a href="/admin/reindex" aria-current={$page.url.pathname === '/admin/reindex' ? 'page' : undefined}
      >{tr('admin.reindex')}</a
    >
  </nav>

  {#if $session && !canAdmin}
    <p class="notice">{tr('admin.forbidden')}</p>
  {:else}
    <div class="content">{@render children()}</div>
  {/if}
</div>

<style>
  .tabs {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    margin-bottom: 1.5rem;
  }
  .tabs a {
    padding: 0.4rem 0.85rem;
    border-radius: 999px;
    text-decoration: none;
    color: var(--fs-text);
    background: var(--fs-surface);
    box-shadow: var(--fs-shadow-soft);
    font-size: 0.9rem;
  }
  .tabs a[aria-current='page'] {
    background: var(--fs-accent-soft);
    color: var(--fs-accent);
    font-weight: 700;
  }
  .notice {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1rem;
  }
</style>
