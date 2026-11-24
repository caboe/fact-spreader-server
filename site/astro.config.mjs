import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// The handbook is always mounted at `/handbook/`; only the site root changes between the
// public deployment and an instance. A GitHub project page adds the repository name.
const base = (process.env.SITE_BASE ?? '/handbook/').replace(/\/*$/, '/');
const site = process.env.SITE_URL ?? 'http://localhost:4321';

export default defineConfig({
  site,
  base,
  trailingSlash: 'always',
  integrations: [
    starlight({
      title: 'Fact Spreader',
      description: 'Handbook for the Fact Spreader fact-checking service.',
      favicon: '/favicon.svg',
      customCss: ['./src/styles/custom.css'],
      lastUpdated: false,
      credits: false,
      // The project supplies `src/pages/404.astro`; do not inject a second route at `/404`.
      disable404Route: true,
      editLink: {
        baseUrl: 'https://github.com/caboe/fact-spreader-server/edit/main/handbook/content/',
      },
      social: [
        {
          icon: 'github',
          label: 'GitHub',
          href: 'https://github.com/caboe/fact-spreader-server',
        },
      ],
      sidebar: [
        {
          label: 'Using Fact Spreader',
          items: [
            { label: 'Overview', link: '/' },
            { label: 'Checking a claim', slug: 'checking-a-claim' },
            { label: 'Reading a report', slug: 'reading-a-report' },
            { label: 'Verdicts', slug: 'verdicts' },
          ],
        },
      ],
    }),
  ],
});
