<script lang="ts">
  import { onMount } from 'svelte';
  import {
    ApiError,
    type ChecklistInfo,
    type InstanceInfo,
    type MethodologyInfo,
    type PatternInfo,
    type PersonaConfig,
    type PublisherOverrideInput,
    deletePersona,
    getInstance,
    getMethodology,
    listPersonaConfig,
    listPublishers,
    moderationTest,
    publisherDiff,
    saveChecklist,
    savePattern,
    savePersona,
    savePublisherOverrides,
  } from '$lib/api';
  import { t } from '$lib/i18n';

  const tr = $derived($t);

  let publishers = $state<{ key: string; publisher?: string | null; grade: string; disputed: boolean; overridden: boolean }[]>([]);
  let publisherOverrides = $state<PublisherOverrideInput[]>([]);
  let publisherInitial = $state<Record<string, { grade: string; disputed: boolean }>>({});
  let diffs = $state<{ key: string; field: string; shipped: unknown; local: unknown }[]>([]);
  let personas = $state<PersonaConfig[]>([]);
  let personaDrafts = $state<Record<string, { tone: string; max_words: number; enabled: boolean }>>({});
  let methodology = $state<MethodologyInfo | null>(null);
  let checklists = $state<Record<string, number>>({});
  let patterns = $state<Record<string, { definition: string; mechanism: string }>>({});
  let instance = $state<InstanceInfo | null>(null);
  let moderation = $state<{ backend: string; flagged: boolean; categories: string[] } | null>(null);
  let error = $state('');
  let notice = $state('');
  let busy = $state('');

  function draftFor(persona: PersonaConfig): { tone: string; max_words: number; enabled: boolean } {
    const existing = personaDrafts[persona.id];
    if (existing) return existing;
    const created = { tone: persona.tone, max_words: persona.max_words, enabled: persona.enabled };
    personaDrafts = { ...personaDrafts, [persona.id]: created };
    return created;
  }

  function patternFor(item: PatternInfo): { definition: string; mechanism: string } {
    const existing = patterns[item.id];
    if (existing) return existing;
    const created = { definition: String(item.definition ?? ''), mechanism: String(item.mechanism ?? '') };
    patterns = { ...patterns, [item.id]: created };
    return created;
  }

  onMount(load);

  async function load(): Promise<void> {
    error = '';
    try {
      const [publisherList, personaList, methodologyInfo, instanceInfo] = await Promise.all([
        listPublishers(),
        listPersonaConfig(),
        getMethodology(),
        getInstance(),
      ]);
      publishers = publisherList.entries ?? [];
      publisherOverrides = (publisherList.overrides ?? [])
        .filter((entry) => entry.key)
        .map((entry) => ({
          key: String(entry.key),
          grade: entry.grade ? String(entry.grade) : undefined,
          disputed: entry.disputed === true,
          note: entry.note ? String(entry.note) : undefined,
        }));
      publisherInitial = Object.fromEntries(
        (publisherList.entries ?? []).map((entry) => [entry.key, { grade: entry.grade, disputed: entry.disputed }]),
      );
      diffs = await publisherDiff().catch(() => []);

      personas = personaList;
      personaDrafts = Object.fromEntries(
        personaList.map((persona) => [
          persona.id,
          { tone: persona.tone, max_words: persona.max_words, enabled: persona.enabled },
        ]),
      );

      methodology = methodologyInfo;
      checklists = Object.fromEntries(
        methodologyInfo.checklists.map((item: ChecklistInfo) => [item.topic, item.staleness_days]),
      );
      patterns = Object.fromEntries(
        methodologyInfo.patterns.map((item: PatternInfo) => [
          item.id,
          { definition: String(item.definition ?? ''), mechanism: String(item.mechanism ?? '') },
        ]),
      );

      instance = instanceInfo;
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    }
  }

  function overrideFor(key: string, patch: Partial<PublisherOverrideInput>): void {
    const existing = publisherOverrides.find((entry) => entry.key === key);
    if (existing) {
      Object.assign(existing, patch);
      publisherOverrides = [...publisherOverrides];
      return;
    }
    publisherOverrides = [...publisherOverrides, { key, ...patch }];
  }

  function resetPublisher(key: string): void {
    const initial = publisherInitial[key];
    publisherOverrides = publisherOverrides.filter((entry) => entry.key !== key);
    if (initial) {
      const entry = publishers.find((item) => item.key === key);
      if (entry) entry.grade = initial.grade;
    }
  }

  async function savePublishers(): Promise<void> {
    busy = 'publishers';
    error = '';
    notice = '';
    try {
      await savePublisherOverrides(
        publisherOverrides.filter((entry) => entry.grade || entry.disputed),
      );
      notice = tr('curation.publishers_saved');
      await load();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function savePersonaRow(persona: PersonaConfig): Promise<void> {
    const draft = personaDrafts[persona.id];
    if (!draft) return;
    busy = persona.id;
    error = '';
    notice = '';
    try {
      await savePersona(persona.id, {
        tone: draft.tone,
        max_words: draft.max_words,
        enabled: draft.enabled,
      });
      notice = tr('curation.persona_saved', { name: persona.name });
      await load();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function removePersona(persona: PersonaConfig): Promise<void> {
    if (!persona.custom) return;
    if (!confirm(tr('curation.persona_delete_confirm', { name: persona.name }))) return;
    busy = persona.id;
    try {
      await deletePersona(persona.id);
      notice = tr('curation.persona_deleted');
      await load();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function saveChecklistRow(item: ChecklistInfo): Promise<void> {
    busy = item.topic;
    error = '';
    notice = '';
    try {
      await saveChecklist(item.topic, { staleness_days: checklists[item.topic] ?? item.staleness_days });
      notice = tr('curation.checklist_saved', { topic: item.name });
      await load();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function savePatternRow(item: PatternInfo): Promise<void> {
    const draft = patterns[item.id];
    if (!draft) return;
    busy = item.id;
    error = '';
    notice = '';
    try {
      await savePattern(item.id, {
        definition: draft.definition || undefined,
        mechanism: draft.mechanism || undefined,
      });
      notice = tr('curation.pattern_saved', { id: item.id });
      await load();
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }

  async function runModeration(): Promise<void> {
    busy = 'moderation';
    error = '';
    moderation = null;
    try {
      moderation = await moderationTest();
      notice = moderation.flagged ? tr('curation.moderation_failed') : tr('curation.moderation_ok');
    } catch (cause) {
      error = cause instanceof ApiError ? cause.message : tr('common.error');
    } finally {
      busy = '';
    }
  }
</script>

<svelte:head><title>{tr('curation.title')} · Fact Spreader</title></svelte:head>

<h1>{tr('curation.title')}</h1>
<p class="intro">{tr('curation.intro')}</p>

{#if error}<p class="error" role="alert">{error}</p>{/if}
{#if notice}<p class="ok" role="status">{notice}</p>{/if}

<section class="panel">
  <h2>{tr('curation.moderation')}</h2>
  <p class="meta">{tr('curation.moderation_hint')}</p>
  <div class="row">
    <button type="button" onclick={runModeration} disabled={busy === 'moderation'}>
      {tr('curation.moderation_run')}
    </button>
    {#if moderation}
      <span class="badge" class:pass={!moderation.flagged} class:fail={moderation.flagged}>
        {moderation.flagged ? tr('curation.moderation_failed') : tr('curation.moderation_ok')}
      </span>
      <span class="meta">{moderation.backend}{#if moderation.categories.length} · {moderation.categories.join(', ')}{/if}</span>
    {/if}
  </div>
</section>

<section class="panel">
  <h2>{tr('curation.languages')}</h2>
  <p class="meta">
    {tr('curation.languages_response')}: {instance?.supported_response_languages?.join(', ') || '—'}
  </p>
  <p class="meta">
    {tr('curation.languages_corpus')}: {instance?.supported_corpus_languages?.join(', ') || '—'}
  </p>
  <p class="meta">{tr('curation.languages_hint')}</p>
</section>

<section class="panel">
  <h2>{tr('curation.publishers')}</h2>
  <p class="meta">{tr('curation.publishers_hint')}</p>
  <table>
    <thead>
      <tr><th>{tr('curation.publisher')}</th><th>{tr('curation.grade')}</th><th>{tr('curation.disputed')}</th><th></th></tr>
    </thead>
    <tbody>
      {#each publishers as entry}
        <tr>
          <td>{entry.publisher ?? entry.key}<div class="meta mono">{entry.key}</div></td>
          <td>
            <select
              value={entry.grade}
              aria-label={`${tr('curation.grade')} ${entry.publisher ?? entry.key}`}
              onchange={(event) => {
                const grade = (event.currentTarget as HTMLSelectElement).value;
                entry.grade = grade;
                overrideFor(entry.key, { grade });
              }}
            >
              {#each ['A', 'B', 'C', 'D'] as grade}
                <option value={grade}>{grade}</option>
              {/each}
            </select>
          </td>
          <td>
            <input
              type="checkbox"
              checked={entry.disputed}
              aria-label={`${tr('curation.disputed')} ${entry.publisher ?? entry.key}`}
              onchange={(event) => {
                const disputed = (event.currentTarget as HTMLInputElement).checked;
                entry.disputed = disputed;
                overrideFor(entry.key, { disputed });
              }}
            />
          </td>
          <td class="right">
            {#if entry.overridden}
              <button type="button" class="link" onclick={() => resetPublisher(entry.key)}>
                {tr('curation.reset')}
              </button>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
  <button type="button" onclick={savePublishers} disabled={busy === 'publishers'}>
    {tr('curation.save_publishers')}
  </button>
  {#if diffs.length > 0}
    <h3>{tr('curation.diff')}</h3>
    <ul class="records">
      {#each diffs as diff}
        <li>
          <span class="mono">{diff.key}</span> · {diff.field}: {String(diff.shipped)} → {String(diff.local)}
        </li>
      {/each}
    </ul>
  {/if}
</section>

<section class="panel">
  <h2>{tr('curation.personas')}</h2>
  <p class="meta">{tr('curation.personas_hint')}</p>
  <table>
    <thead>
      <tr><th>{tr('curation.persona')}</th><th>{tr('curation.tone')}</th><th>{tr('curation.max_words')}</th><th>{tr('common.enabled')}</th><th></th></tr>
    </thead>
    <tbody>
      {#each personas as persona}
        {@const draft = draftFor(persona)}
        <tr>
          <td>{persona.name}<div class="meta mono">{persona.id}{#if persona.custom} · {tr('curation.custom')}{/if}</div></td>
          <td><input type="text" bind:value={draft.tone} aria-label={`${tr('curation.tone')} ${persona.name}`} /></td>
          <td><input type="number" min="40" max="1000" bind:value={draft.max_words} aria-label={`${tr('curation.max_words')} ${persona.name}`} /></td>
          <td><input type="checkbox" bind:checked={draft.enabled} aria-label={`${tr('common.enabled')} ${persona.name}`} /></td>
          <td class="right actions">
            <button type="button" onclick={() => savePersonaRow(persona)} disabled={busy === persona.id}>
              {tr('common.save')}
            </button>
            {#if persona.custom}
              <button type="button" class="link" onclick={() => removePersona(persona)}>{tr('common.delete')}</button>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</section>

<section class="panel">
  <h2>{tr('curation.methodology')}</h2>
  <p class="meta">{tr('curation.methodology_hint')} · {tr('curation.patterns_version')}: {methodology?.patterns_version}</p>
  <h3>{tr('curation.checklists')}</h3>
  <table>
    <thead>
      <tr><th>{tr('curation.topic')}</th><th>{tr('curation.staleness')}</th><th></th></tr>
    </thead>
    <tbody>
      {#each methodology?.checklists ?? [] as item}
        <tr>
          <td>{item.name}<div class="meta mono">{item.topic} · {item.confounders.length} {tr('curation.confounders')}</div></td>
          <td><input type="number" min="30" max="3650" bind:value={checklists[item.topic]} aria-label={`${tr('curation.staleness')} ${item.name}`} /></td>
          <td class="right">
            <button type="button" onclick={() => saveChecklistRow(item)} disabled={busy === item.topic}>
              {tr('common.save')}
            </button>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>

  <details>
    <summary>{tr('curation.patterns')}</summary>
    {#each methodology?.patterns ?? [] as item}
      {@const draft = patternFor(item)}
      <div class="pattern">
        <p class="mono">{item.id} · {String(item.name ?? '')}</p>
        <label class="field">
          <span>{tr('curation.definition')}</span>
          <textarea rows="2" bind:value={draft.definition}></textarea>
        </label>
        <label class="field">
          <span>{tr('curation.mechanism')}</span>
          <textarea rows="2" bind:value={draft.mechanism}></textarea>
        </label>
        <button type="button" onclick={() => savePatternRow(item)} disabled={busy === item.id}>
          {tr('common.save')}
        </button>
      </div>
    {/each}
  </details>
</section>

<style>
  .intro {
    max-width: 60rem;
    color: var(--fs-muted);
  }
  .panel {
    background: var(--fs-surface);
    border-radius: var(--fs-radius);
    box-shadow: var(--fs-shadow-soft);
    padding: 1.1rem;
    margin-bottom: 1rem;
    display: grid;
    gap: 0.7rem;
    max-width: 72rem;
  }
  .panel h2,
  .panel h3 {
    margin: 0;
  }
  table {
    border-collapse: collapse;
    width: 100%;
    font-size: 0.9rem;
  }
  th {
    text-align: left;
    color: var(--fs-muted);
    font-weight: 600;
    padding: 0.35rem 0.3rem;
  }
  td {
    padding: 0.35rem 0.3rem;
    vertical-align: top;
  }
  td input[type='text'],
  td input[type='number'],
  select,
  textarea {
    font: inherit;
    padding: 0.35rem 0.45rem;
    border-radius: 0.4rem;
    border: 1px solid var(--fs-border);
    background: var(--fs-bg);
    color: var(--fs-text);
    width: 100%;
  }
  td select {
    width: auto;
  }
  .field {
    display: grid;
    gap: 0.2rem;
  }
  .field span {
    color: var(--fs-muted);
    font-size: 0.82rem;
  }
  .pattern {
    border-top: 1px solid var(--fs-border);
    padding: 0.6rem 0;
    display: grid;
    gap: 0.4rem;
  }
  .actions {
    display: flex;
    gap: 0.4rem;
    justify-content: flex-end;
    flex-wrap: wrap;
  }
  button {
    font: inherit;
    padding: 0.4rem 0.85rem;
    border-radius: 0.5rem;
    border: none;
    background: var(--fs-accent);
    color: var(--fs-accent-contrast);
    font-weight: 600;
    cursor: pointer;
  }
  button:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
  button.link {
    background: none;
    color: var(--fs-accent);
    padding: 0.2rem;
  }
  .badge {
    padding: 0.2rem 0.6rem;
    border-radius: 999px;
    font-size: 0.82rem;
    background: var(--fs-bg);
  }
  .badge.pass {
    color: var(--fs-true);
  }
  .badge.fail {
    color: var(--fs-false);
  }
  .meta {
    color: var(--fs-muted);
    font-size: 0.82rem;
    margin: 0;
  }
  .mono {
    font-family: var(--fs-mono, ui-monospace, monospace);
  }
  .row {
    display: flex;
    gap: 0.6rem;
    align-items: center;
    flex-wrap: wrap;
  }
  .records {
    margin: 0;
    padding-left: 1rem;
    font-size: 0.85rem;
  }
  .right {
    text-align: right;
  }
  .error {
    color: var(--fs-false);
  }
  .ok {
    color: var(--fs-true);
  }
</style>
