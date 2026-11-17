<script lang="ts">
  import { onMount } from 'svelte';
  import { ApiError, chatStream, getSession, listPersonas } from '$lib/api';
  import { session } from '$lib/session';
  import { t } from '$lib/i18n';
  const tr = $derived($t);

  interface Message {
    role: 'user' | 'assistant';
    content: string;
  }

  let messages = $state<Message[]>([]);
  let draft = $state('');
  let busy = $state(false);
  let error = $state('');
  let jobId = $state<string | null>(null);
  let personas = $state<{ id: string; label: string }[]>([]);
  let persona = $state('factcheck:analyst');

  onMount(async () => {
    if (!$session) {
      try {
        session.set(await getSession());
      } catch {
        session.set(null);
      }
    }
    personas = await listPersonas().catch(() => []);
  });

  async function send(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    if (!$session) {
      error = tr('check.requires_login');
      return;
    }
    error = '';
    jobId = null;
    draft = '';
    busy = true;
    messages = [...messages, { role: 'user', content: text }];
    let answer = '';
    messages = [...messages, { role: 'assistant', content: '' }];
    try {
      const result = await chatStream(
        persona,
        messages
          .filter((message) => message.content)
          .map((message) => ({ role: message.role, content: message.content })),
        (chunk) => {
          answer += chunk;
          messages = [...messages.slice(0, -1), { role: 'assistant', content: answer }];
        },
      );
      jobId = result.jobId;
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>{tr('chat.title')} · Fact Spreader</title></svelte:head>

<h1>{tr('chat.title')}</h1>
<p>{tr('chat.intro')}</p>

<label class="persona">
  <span>{tr('check.persona')}</span>
  <select bind:value={persona}>
    {#each personas as option}
      <option value={option.id}>{option.label}</option>
    {/each}
  </select>
</label>

<div class="thread" aria-live="polite">
  {#each messages as message}
    <article class:user={message.role === 'user'} class="message">
      <p class="role">{message.role === 'user' ? tr('check.text') : tr('chat.answer')}</p>
      <p class="content">{message.content || '…'}</p>
    </article>
  {/each}
</div>

{#if jobId}
  <p><a href={`/report/${jobId}`}>{tr('chat.link')}</a></p>
{/if}
{#if error}<p class="error" role="alert">{error}</p>{/if}

<form class="composer" onsubmit={send}>
  <label class="field">
    <span>{tr('chat.placeholder')}</span>
    <textarea rows="3" bind:value={draft}></textarea>
  </label>
  <button type="submit" disabled={busy}>
    {busy ? tr('check.running') : tr('chat.send')}
  </button>
</form>

<style>
  .persona {
    display: flex;
    gap: 0.5rem;
    align-items: center;
    margin: 1rem 0;
  }
  select,
  textarea {
    padding: 0.55rem 0.7rem;
    border-radius: 0.5rem;
    border: 1px solid var(--fs-border);
    background: var(--fs-bg);
    color: var(--fs-text);
    font: inherit;
  }
  .thread {
    display: grid;
    gap: 0.75rem;
    margin: 1rem 0;
    max-width: 55rem;
  }
  .message {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 0.9rem 1.1rem;
  }
  .message.user {
    border-left: 4px solid var(--fs-accent);
  }
  .role {
    margin: 0 0 0.3rem;
    color: var(--fs-muted);
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .content {
    margin: 0;
    white-space: pre-wrap;
  }
  .composer {
    display: grid;
    gap: 0.5rem;
    max-width: 55rem;
  }
  .field {
    display: grid;
    gap: 0.3rem;
  }
  .field span {
    color: var(--fs-muted);
    font-size: 0.85rem;
  }
  button {
    justify-self: start;
    padding: 0.55rem 1.2rem;
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
  }
</style>
