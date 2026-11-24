# Fact Spreader handbook

Source of truth for the user and operator handbook. The website under [`site/`](../site/)
renders these files; the same build is bundled into the Caddy image and served at
`/handbook/` by every instance.

Content is licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
The site build code is licensed under AGPL-3.0-or-later like the rest of the repository.

## Layout

```
handbook/
  content/            Starlight pages, English
  README.md           this file
```

`site/` copies `content/` into its content collection before every build. Never edit the
copy under `site/src/content/docs/`; it is generated and gitignored.

## Audience split

The handbook serves two audiences:

| Audience | Directory | Examples |
| --- | --- | --- |
| Users | `content/` | checking a claim, reading a report, research, archive, extension |
| Operators | `content/operating/` | setup, providers, budgets, retention, backup, security |

Operator pages live under `content/operating/` so the sidebar can group them without a
second taxonomy. The first release covers the user pages; operator pages are derived from
`docs/OPERATING.md` and `docs/SECURITY.md` and follow the same rules.

## Page contract

Every page is Markdown with Starlight frontmatter:

```yaml
---
title: Reading a report
description: The sections of a claim report, what the evidence shows, and what the warnings mean.
---
```

- `title` and `description` are required. The description is used for search results and
  link previews; keep it one sentence.
- Use relative links between pages (`./verdicts/`, `../reading-a-report/`). Absolute links
  break when the handbook is mounted at `/handbook/` on an instance but at
  `/<repository>/handbook/` on the public site.
- Do not link to `docs/`, `PROTOCOL.md` or other repository files with relative paths. Link
  to the file on GitHub with an absolute URL, or leave the detail out.
- One page answers one question. Long procedures are split into steps, not stacked
  paragraphs.

## Writing rules

- English, present tense, second person. Say what the user sees and does, not how the code
  is structured.
- Do not promise behaviour that `PURPOSE.md` does not require. When in doubt, cite the
  report or leave the detail out.
- Verdict names, warning codes and API field names are literal identifiers. Put them in
  backticks and spell them exactly as the API does.
- Do not describe internal model prompts or provider details in user pages.
- Screenshots come from `docs/screenshots/` (Playwright). The public build copies the ones
  it needs; do not commit duplicate copies.

## Keeping it current

Nothing derives the handbook from the application. The build guarantees that the handbook
shipped with an instance matches that commit; it does not know whether the text still
describes the behaviour. Update the affected page in the same change:

| Change | Page |
| --- | --- |
| Input types, limits, pipeline, fast mode, languages | `checking-a-claim.md` |
| Report sections, evidence display, warnings, versions | `reading-a-report.md` |
| Verdict values, gate, staleness, contradiction rules | `verdicts.md` |
| Setup, providers, budgets, retention, backup, security | `operating/…` |
| Visible UI screenshots | rerun Playwright, commit under `docs/screenshots/` |
| Product claims and landing copy | `site/landing/index.html` (hand-written) |

If a change under `web/src/` leaves every handbook page untouched, say why in the PR body.

## Checks

`make install` installs the site workspace. `make site-check` type-checks it, builds the
handbook, runs the link checker, then composes and checks the public tree. `make verify`
includes it. The link checker runs on the built HTML, so it catches missing pages and
broken links between pages even when the Markdown looks fine.

The public build additionally composes the product landing page and the handbook into one
static tree:

```bash
cd site
pnpm build
pnpm build:public
```

Output goes to `site/dist-public/` (gitignored). The site is always mounted under
`/handbook/`; `SITE_BASE` changes only the prefix (a GitHub project page uses
`/<repository>/handbook/`). `make site-check` builds and checks both the mounted handbook
and the composed public tree.
