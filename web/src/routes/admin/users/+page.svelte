<script lang="ts">
  import { onMount } from 'svelte';
  import { ApiError, createUser, listUsers, updateUser, type UserInfo } from '$lib/api';
  import { t } from '$lib/i18n';

  const tr = $derived($t);
  const ROLES = ['admin', 'editor', 'researcher', 'user'];
  let users = $state<UserInfo[]>([]);
  let error = $state('');
  let notice = $state('');
  let busy = $state(false);
  let form = $state({ email: '', display_name: '', password: '', roles: ['user'] });
  let selected = $state('');
  let limits = $state({ requests_per_day: '', text_chars: '', max_file_bytes: '', max_batch_files: '' });
  let role = $state('user');

  onMount(load);

  async function load(): Promise<void> {
    error = '';
    try {
      users = (await listUsers()).data;
      const current = users.find((user) => user.id === selected) ?? users[0];
      if (current) select(current);
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    }
  }

  function select(user: UserInfo): void {
    selected = user.id;
    limits = {
      requests_per_day: user.requests_per_day?.toString() ?? '',
      text_chars: user.text_chars?.toString() ?? '',
      max_file_bytes: user.max_file_bytes?.toString() ?? '',
      max_batch_files: user.max_batch_files?.toString() ?? '',
    };
    role = (user.roles ?? [])[0] ?? 'user';
  }

  async function create(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    busy = true;
    error = '';
    notice = '';
    try {
      await createUser(form);
      notice = tr('admin.user_created');
      form = { email: '', display_name: '', password: '', roles: ['user'] };
      await load();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = false;
    }
  }

  async function save(): Promise<void> {
    if (!selected) return;
    busy = true;
    error = '';
    notice = '';
    const body: Record<string, unknown> = { roles: [role] };
    for (const [field, value] of Object.entries(limits)) {
      if (value !== '') body[field] = Number(value);
    }
    try {
      await updateUser(selected, body);
      notice = tr('admin.user_saved');
      await load();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = false;
    }
  }

  async function toggleActive(user: UserInfo): Promise<void> {
    busy = true;
    try {
      await updateUser(user.id, { is_active: !user.is_active });
      await load();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = false;
    }
  }
</script>

<h1>{tr('admin.users')}</h1>
{#if error}<p class="error" role="alert">{error}</p>{/if}
{#if notice}<p class="ok" role="status">{notice}</p>{/if}

<section class="panel">
  <table>
    <thead>
      <tr>
        <th>{tr('admin.email')}</th><th>{tr('admin.name')}</th><th>{tr('admin.roles')}</th
        ><th>TOTP</th><th>{tr('admin.active')}</th><th></th>
      </tr>
    </thead>
    <tbody>
      {#each users as user}
        <tr>
          <td>{user.email}</td>
          <td>{user.display_name}</td>
          <td>{(user.roles ?? []).join(', ')}</td>
          <td>{user.totp_enabled ? tr('common.yes') : tr('common.no')}</td>
          <td>{user.is_active ? tr('common.yes') : tr('common.no')}</td>
          <td class="right">
            <button type="button" class="ghost" onclick={() => select(user)}>{tr('admin.edit')}</button>
            <button type="button" class="ghost" onclick={() => toggleActive(user)} disabled={busy}>
              {user.is_active ? tr('admin.deactivate') : tr('admin.activate')}
            </button>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</section>

<div class="columns">
  <section class="panel">
    <h2>{tr('admin.create_user')}</h2>
    <form onsubmit={create}>
      <label><span>{tr('admin.email')}</span><input type="email" bind:value={form.email} required /></label>
      <label><span>{tr('admin.name')}</span><input type="text" bind:value={form.display_name} required /></label>
      <label>
        <span>{tr('login.password')}</span>
        <input type="password" bind:value={form.password} required autocomplete="new-password" />
      </label>
      <label>
        <span>{tr('admin.roles')}</span>
        <select bind:value={form.roles[0]}>
          {#each ROLES as name}<option value={name}>{name}</option>{/each}
        </select>
      </label>
      <button type="submit" disabled={busy}>{tr('admin.create')}</button>
      <p class="hint">{tr('admin.password_hint')}</p>
    </form>
  </section>

  <section class="panel">
    <h2>{tr('admin.edit_user')}</h2>
    {#if users.length === 0}
      <p>—</p>
    {:else}
      <label class="block">
        <span>{tr('admin.email')}</span>
        <select
          value={selected}
          onchange={(event) => {
            const user = users.find((entry) => entry.id === (event.currentTarget as HTMLSelectElement).value);
            if (user) select(user);
          }}
        >
          {#each users as user}<option value={user.id}>{user.email}</option>{/each}
        </select>
      </label>
      <div class="grid">
        <label><span>{tr('admin.requests_per_day')}</span><input type="number" min="1" bind:value={limits.requests_per_day} /></label>
        <label><span>{tr('admin.text_chars')}</span><input type="number" min="1" bind:value={limits.text_chars} /></label>
        <label><span>{tr('admin.max_file_bytes')}</span><input type="number" min="1" bind:value={limits.max_file_bytes} /></label>
        <label><span>{tr('admin.max_batch_files')}</span><input type="number" min="1" bind:value={limits.max_batch_files} /></label>
        <label>
          <span>{tr('admin.roles')}</span>
          <select bind:value={role}>
            {#each ROLES as name}<option value={name}>{name}</option>{/each}
          </select>
        </label>
      </div>
      <button type="button" onclick={save} disabled={busy}>{tr('admin.save')}</button>
    {/if}
  </section>
</div>

<style>
  .columns {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(22rem, 1fr));
    gap: 1rem;
  }
  .panel {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1.2rem 1.35rem;
    margin-bottom: 1rem;
    overflow-x: auto;
  }
  h2 {
    margin: 0 0 0.75rem;
    font-size: 1rem;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
  }
  th {
    text-align: left;
    color: var(--fs-muted);
    padding: 0.3rem 0.5rem;
    white-space: nowrap;
  }
  td {
    padding: 0.45rem 0.5rem;
    border-top: 1px solid color-mix(in srgb, var(--fs-border) 45%, transparent);
  }
  .right {
    text-align: right;
    white-space: nowrap;
  }
  form {
    display: grid;
    gap: 0.75rem;
    max-width: 26rem;
  }
  label {
    display: grid;
    gap: 0.25rem;
    font-size: 0.85rem;
  }
  .block {
    margin-bottom: 0.75rem;
  }
  .grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
  }
  input,
  select {
    padding: 0.5rem 0.65rem;
    border-radius: 0.5rem;
    border: 1px solid color-mix(in srgb, var(--fs-border) 60%, transparent);
    background: var(--fs-bg);
    color: var(--fs-text);
    font: inherit;
  }
  button {
    padding: 0.5rem 0.9rem;
    border-radius: 0.5rem;
    border: none;
    background: var(--fs-accent);
    color: var(--fs-accent-contrast);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }
  button.ghost {
    background: var(--fs-bg);
    color: var(--fs-text);
    box-shadow: var(--fs-shadow-soft);
    margin-left: 0.25rem;
  }
  button:disabled {
    opacity: 0.6;
    cursor: wait;
  }
  .hint {
    color: var(--fs-muted);
    font-size: 0.8rem;
    margin: 0;
  }
  .error {
    color: var(--fs-false);
  }
  .ok {
    color: var(--fs-true);
  }
</style>
