// Compose the public site: the product landing page at the site root and the handbook under
// `/handbook/`. Run `pnpm build` first; the instance image only uses `dist/`, which is
// always built with `base = '/handbook/'`.
import { access, cp, mkdir, rm, writeFile } from 'node:fs/promises';

const out = new URL('../dist-public/', import.meta.url);
const dist = new URL('../dist/', import.meta.url);
const shots = new URL('../../docs/screenshots/', import.meta.url);

try {
  await access(new URL('index.html', dist));
} catch {
  console.error('site: run `pnpm build` before `pnpm build:public`');
  process.exit(1);
}

await rm(out, { recursive: true, force: true });
await mkdir(out, { recursive: true });

// Landing page first, then the handbook below it. Landing links are relative, so the same
// tree works at a domain root and under a GitHub project path.
await cp(new URL('../landing/', import.meta.url), out, { recursive: true });
await cp(dist, new URL('handbook/', out), { recursive: true });
await cp(new URL('favicon.svg', dist), new URL('favicon.svg', out));
// GitHub Pages looks for 404.html at the site root, not below the handbook mount.
await cp(new URL('404.html', dist), new URL('404.html', out));
// GitHub Pages must serve `_astro` directories verbatim.
await writeFile(new URL('.nojekyll', out), '');

// Screenshots stay canonical in docs/screenshots/ and are copied only into the artifact.
const images = [
  ['phase-7/report-light.png', 'report.png'],
  ['phase-7/check-light.png', 'check.png'],
  ['phase-8/editorial-light.png', 'editorial.png'],
];
await mkdir(new URL('assets/', out), { recursive: true });
for (const [source, name] of images) {
  await cp(new URL(source, shots), new URL(`assets/${name}`, out));
}

console.log('site: public build written to site/dist-public/');
