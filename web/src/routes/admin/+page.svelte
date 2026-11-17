<script lang="ts">
  import { onMount } from 'svelte';
  import { ApiError, listModels, listProviders, listRoles, listUsers } from '$lib/api';
  import { t } from '$lib/i18n';

  const tr = $derived($t);
  let counts = $state({ providers: 0, models: 0, assigned: 0, unsatisfied: 0, users: 0 });
  let error = $state('');

  onMount(async () => {
    try {
      const [providers, models, roles, users] = await Promise.all([
        listProviders(),
        listModels(),
        listRoles(),
        listUsers(),
      ]);
      counts = {
        providers: providers.length,
        models: models.length,
        assigned: roles.filter((role) => role.model).length,
        unsatisfied: roles.filter((role) => role.model && !role.suitable).length,
        users: users.data.length,
      };
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    }
  });
</script>

<h1>{tr('admin.overview')}</h1>
{#if error}<p class="error" role="alert">{error}</p>{/if}

<div class="cards">
  <a class="card" href="/admin/providers">
    <strong>{counts.providers}</strong>
    <span>{tr('admin.providers')}</span>
  </a>
  <a class="card" href="/admin/providers">
    <strong>{counts.models}</strong>
    <span>{tr('admin.models')}</span>
  </a>
  <a class="card" href="/admin/roles">
    <strong>{counts.assigned}/7</strong>
    <span>{tr('admin.assigned_roles')}</span>
  </a>
  <a class="card" href="/admin/roles">
    <strong>{counts.unsatisfied}</strong>
    <span>{tr('admin.unsatisfied_roles')}</span>
  </a>
  <a class="card" href="/admin/users">
    <strong>{counts.users}</strong>
    <span>{tr('admin.users')}</span>
  </a>
</div>
<p class="hint">{tr('admin.overview_hint')}</p>

<style>
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
    gap: 1rem;
  }
  .card {
    display: grid;
    gap: 0.25rem;
    padding: 1.1rem 1.2rem;
    border-radius: var(--fs-radius);
    background: var(--fs-surface);
    box-shadow: var(--fs-shadow-soft);
    text-decoration: none;
    color: var(--fs-text);
  }
  .card strong {
    font-size: 1.8rem;
    color: var(--fs-accent);
  }
  .hint {
    margin-top: 1.5rem;
    color: var(--fs-muted);
  }
  .error {
    color: var(--fs-false);
  }
</style>
