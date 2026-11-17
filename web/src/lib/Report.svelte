<script lang="ts">
  import type { CheckResponse } from '$lib/api';
  import { t } from '$lib/i18n';
  const tr = $derived($t);

  let { response }: { response: CheckResponse } = $props();
  const result = $derived(response.result);

  const MARKS: Record<string, string> = {
    true: '✓',
    true_but_misleading: '!',
    partially_false: '±',
    false: '×',
    contested: '⚖',
    insufficient_evidence: '?',
    not_checkable: '–',
  };
  const COLORS: Record<string, string> = {
    true: 'var(--fs-true)',
    true_but_misleading: 'var(--fs-misleading)',
    partially_false: 'var(--fs-misleading)',
    false: 'var(--fs-false)',
    contested: 'var(--fs-contested)',
    insufficient_evidence: 'var(--fs-insufficient)',
    not_checkable: 'var(--fs-insufficient)',
  };

  function verdictText(value: string | null | undefined): string {
    return value ? $t(`verdict.${value}`) : $t('report.verdict');
  }
  function mark(value: string | null | undefined): string {
    return MARKS[value ?? ''] ?? '?';
  }
  function color(value: string | null | undefined): string {
    return COLORS[value ?? ''] ?? 'var(--fs-insufficient)';
  }
  function warningText(code: string, message?: string | null): string {
    return message ? `${code}: ${message}` : code;
  }
  function plain(text: string): string {
    return text
      .replace(/^#{1,6}\s+/gm, '')
      .replace(/^>\s?/gm, '')
      .replace(/\*\*(.*?)\*\*/g, '$1')
      .replace(/`/g, '');
  }
  const narrativeText = $derived(plain(response.rendering?.text ?? ''));
</script>

<article class="report" aria-labelledby="verdict-heading">
  <header class="verdict" style={`border-color:${color(result.overall_verdict)}`}>
    <span class="mark" aria-hidden="true" style={`color:${color(result.overall_verdict)}`}
      >{mark(result.overall_verdict)}</span
    >
    <div>
      <p class="label">{tr('report.verdict')}</p>
      <h2 id="verdict-heading" style={`color:${color(result.overall_verdict)}`}>
        {verdictText(result.overall_verdict)}
      </h2>
      {#if result.overall_explanation}
        <p class="explanation">{result.overall_explanation}</p>
      {/if}
      {#if result.preliminary}
        <p class="pending">{tr('report.narrative_pending')}</p>
      {/if}
    </div>
  </header>

  {#if result.warnings && result.warnings.length > 0}
    <section class="warnings" aria-labelledby="warnings-heading">
      <h3 id="warnings-heading">{tr('report.warnings')}</h3>
      <ul>
        {#each result.warnings as warning}
          <li>{warningText(warning.code, warning.message)}</li>
        {/each}
      </ul>
    </section>
  {/if}

  <section aria-labelledby="substance-heading">
    <h3 id="substance-heading">{tr('report.substance')}</h3>
    {#if (result.statements ?? []).length === 0}
      <p>{tr('report.no_evidence')}</p>
    {/if}
    {#each result.statements ?? [] as statement}
      <article class="statement">
        <h4>{statement.text}</h4>
        <p class="statement-verdict" style={`color:${color(statement.verdict)}`}>
          <span aria-hidden="true">{mark(statement.verdict)}</span>
          {verdictText(statement.verdict)}
        </p>
        {#if statement.verdict_rationale}
          <p>{statement.verdict_rationale}</p>
        {/if}
        {#if (statement.what_is_true ?? []).length > 0}
          <h5>{tr('report.true')}</h5>
          <ul>
            {#each statement.what_is_true ?? [] as item}
              <li>{item.text}</li>
            {/each}
          </ul>
        {/if}
        {#if (statement.what_is_missing ?? []).length > 0}
          <h5>{tr('report.missing')}</h5>
          <ul>
            {#each statement.what_is_missing ?? [] as item}
              <li>{item.text}</li>
            {/each}
          </ul>
        {/if}
        {#if (statement.what_is_unverifiable ?? []).length > 0}
          <h5>{tr('report.unverifiable')}</h5>
          <ul>
            {#each statement.what_is_unverifiable ?? [] as item}
              <li>{item.text} ({item.reason})</li>
            {/each}
          </ul>
        {/if}
      </article>
    {/each}
  </section>

  {#if response.rendering?.text}
    <section class="narrative" aria-labelledby="narrative-heading">
      <h3 id="narrative-heading">{tr('report.narrative')}</h3>
      <p class="narrative-text">{narrativeText}</p>
    </section>
  {:else if result.status === 'complete'}
    <p class="pending">{tr('report.narrative_pending')}</p>
  {/if}

  {#if (result.evidence ?? []).length > 0}
    <section aria-labelledby="evidence-heading">
      <h3 id="evidence-heading">{tr('report.evidence')}</h3>
      <ol class="evidence">
        {#each result.evidence ?? [] as item}
          <li>
            <p class="source">
              [{item.id}] {item.provenance.publisher}
              {#if item.provenance.publication_date}· {item.provenance.publication_date}{/if}
              · {item.provenance.source_quality}
            </p>
            <p class="passage">{plain(item.passage)}</p>
            {#if item.provenance.url}
              <a href={item.provenance.url} rel="noreferrer noopener" target="_blank"
                >{tr('report.open_source')}</a
              >
            {/if}
          </li>
        {/each}
      </ol>
    </section>
  {/if}
</article>

<style>
  .report {
    display: grid;
    gap: 1.5rem;
    max-width: 60rem;
  }
  .verdict {
    display: flex;
    gap: 1rem;
    align-items: flex-start;
    border: 2px solid var(--fs-border);
    border-radius: var(--fs-radius);
    padding: 1rem;
    background: var(--fs-surface);
  }
  .mark {
    font-size: 2rem;
    line-height: 1;
    font-weight: 700;
  }
  .label {
    margin: 0;
    color: var(--fs-muted);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  h2 {
    margin: 0.1rem 0 0.4rem;
    font-size: 1.5rem;
  }
  .explanation {
    margin: 0;
  }
  .statement {
    border-top: 1px solid var(--fs-border);
    padding-top: 1rem;
    margin-top: 1rem;
  }
  .statement-verdict {
    font-weight: 600;
    margin: 0.35rem 0;
  }
  h3 {
    font-size: 1.05rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--fs-muted);
  }
  h4 {
    margin: 0;
    font-size: 1rem;
  }
  h5 {
    margin: 0.75rem 0 0.25rem;
    font-size: 0.9rem;
  }
  ul,
  ol {
    margin: 0.25rem 0;
    padding-left: 1.4rem;
  }
  .evidence {
    display: grid;
    gap: 0.75rem;
    padding-left: 1.2rem;
  }
  .evidence li {
    background: var(--fs-surface);
    border: 1px solid var(--fs-border);
    border-radius: var(--fs-radius);
    padding: 0.75rem;
  }
  .source {
    margin: 0 0 0.35rem;
    font-weight: 600;
    font-size: 0.85rem;
  }
  .passage {
    margin: 0;
    white-space: pre-wrap;
  }
  .warnings {
    background: var(--fs-surface);
    border: 1px solid var(--fs-border);
    border-radius: var(--fs-radius);
    padding: 0.75rem 1rem;
  }
  .narrative-text {
    white-space: pre-wrap;
  }
  .pending {
    color: var(--fs-muted);
    font-style: italic;
  }
</style>
