// Copy the canonical handbook into the Starlight content collection.
//
// The handbook lives at the repository root so it is reviewable as content, not as site
// source. Starlight only reads `src/content/docs/`, so this script mirrors the tree before
// every dev run, check and build. The destination is gitignored; never edit it.
import { cp, mkdir, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const source = fileURLToPath(new URL('../../handbook/content/', import.meta.url));
const target = fileURLToPath(new URL('../src/content/docs/', import.meta.url));

await rm(target, { recursive: true, force: true });
await mkdir(target, { recursive: true });
await cp(source, target, { recursive: true });

console.log(`handbook: synced handbook/content/ to site/src/content/docs/`);
