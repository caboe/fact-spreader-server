import { defineCollection } from 'astro:content';
import { z } from 'astro/zod';
import { docsLoader, i18nLoader } from '@astrojs/starlight/loaders';
import { docsSchema, i18nSchema } from '@astrojs/starlight/schema';

// Content lives in `handbook/content/` and is copied into this collection before every
// build by `scripts/sync-handbook.mjs`. `site/src/content/docs/` is generated.
//
// The description is required: it is the page summary used by search and link previews,
// and a missing one is invisible in review but visible in every result.
//
// The i18n collection is declared, although the handbook ships in English only, because
// Starlight warns about every build when the collection is absent. `en.json` is empty.
export const collections = {
  docs: defineCollection({
    loader: docsLoader(),
    schema: docsSchema({
      extend: z.object({
        description: z.string().min(20),
      }),
    }),
  }),
  i18n: defineCollection({ loader: i18nLoader(), schema: i18nSchema() }),
};
