// Verify that every internal link in a built site resolves to a file in the artifact.
//
// Two layouts are checked:
//   mounted  the artifact *is* the handbook, served at `--base` (the instance image)
//   site     the artifact is a site root with the handbook below `--base`
//
// Usage:
//   node scripts/check-links.mjs --root dist --mode mounted --base /handbook/
//   node scripts/check-links.mjs --root dist-public --mode site --base /handbook/ --mount /repo/
import { readdir, readFile, stat } from 'node:fs/promises';
import { extname, join, relative, resolve, sep } from 'node:path';

const args = parseArgs(process.argv.slice(2));
const root = resolve(args.root ?? 'dist');
const base = normalizeBase(args.base ?? process.env.SITE_BASE ?? '/handbook/');
const mode = args.mode ?? 'mounted';
// Where the artifact is deployed. GitHub project pages mount it under the repository name.
const mount = normalizeBase(args.mount ?? process.env.SITE_MOUNT ?? '/');
const baseNoSlash = base.slice(0, -1);
const mountNoSlash = mount === '/' ? '' : mount.slice(0, -1);

if (!['mounted', 'site'].includes(mode)) {
  fail(`unknown mode "${mode}" (expected "mounted" or "site")`);
}

const pages = await htmlFiles(root);
if (pages.length === 0) fail(`no HTML files under ${root}`);

let checked = 0;
const broken = [];

for (const file of pages) {
  const html = await readFile(file, 'utf8');
  const page = pageUrl(file);
  for (const match of html.matchAll(/\b(?:href|src)\s*=\s*(?:"([^"]*)"|'([^']*)')/gi)) {
    const raw = (match[1] ?? match[2] ?? '').replace(/&amp;/g, '&').trim();
    if (shouldSkip(raw)) continue;

    const withoutFragment = raw.split('#')[0].split('?')[0];
    if (!withoutFragment) continue;

    checked += 1;
    let urlPath;
    try {
      urlPath = new URL(withoutFragment, `http://site${page}`).pathname;
    } catch {
      broken.push(`${relative(root, file)}: cannot parse "${raw}"`);
      continue;
    }

    if (!(await resolves(urlPath))) {
      broken.push(`${relative(root, file)}: "${raw}" -> ${urlPath}`);
    }
  }
}

if (broken.length > 0) {
  console.error(`check-links: ${broken.length} broken internal link(s) in ${pages.length} pages:\n`);
  for (const line of broken) console.error(`  ${line}`);
  process.exit(1);
}

console.log(`check-links: ${checked} internal links in ${pages.length} pages, all resolve`);

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith('--')) continue;
    const eq = arg.indexOf('=');
    if (eq !== -1) out[arg.slice(2, eq)] = arg.slice(eq + 1);
    else if (argv[i + 1] && !argv[i + 1].startsWith('--')) out[arg.slice(2)] = argv[++i];
    else out[arg.slice(2)] = true;
  }
  return out;
}

function normalizeBase(value) {
  const withSlash = value.startsWith('/') ? value : `/${value}`;
  return withSlash.endsWith('/') ? withSlash : `${withSlash}/`;
}

function fail(message) {
  console.error(`check-links: ${message}`);
  process.exit(1);
}

async function htmlFiles(dir) {
  const out = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...(await htmlFiles(path)));
    else if (entry.isFile() && entry.name.endsWith('.html')) out.push(path);
  }
  return out;
}

/** The URL path a built HTML file is served at. */
function pageUrl(file) {
  const rel = relative(root, file).split(sep).join('/').replace(/index\.html$/, '');
  if (mode === 'site') return `${mountNoSlash}/${rel}`;
  return `/${base.slice(1)}${rel}`;
}

function shouldSkip(raw) {
  if (!raw || raw.startsWith('#')) return true;
  if (raw.startsWith('//')) return true;
  // Any scheme (http, https, mailto, data, javascript) is out of scope.
  return /^[a-z][a-z0-9+.-]*:/i.test(raw);
}

async function resolves(urlPath) {
  for (const candidate of candidates(urlPath)) {
    try {
      if ((await stat(candidate)).isFile()) return true;
    } catch {
      // try the next candidate
    }
  }
  return false;
}

/** Candidate files for a URL path, honoring the mount mode. */
function candidates(urlPath) {
  let rel = urlPath;
  if (mode === 'mounted') {
    if (rel === baseNoSlash || rel === base) rel = '/';
    else if (rel.startsWith(base)) rel = `/${rel.slice(base.length)}`;
  } else if (mount !== '/') {
    if (rel === mountNoSlash || rel === mount) rel = '/';
    else if (rel.startsWith(mount)) rel = `/${rel.slice(mount.length)}`;
    else return [];
  }

  let decoded;
  try {
    decoded = decodeURIComponent(rel.replace(/^\/+/, ''));
  } catch {
    decoded = rel.replace(/^\/+/, '');
  }
  if (decoded.split('/').includes('..')) return [];

  const target = resolve(root, decoded);
  if (target !== root && !target.startsWith(root + sep)) return [];

  if (decoded === '' || urlPath.endsWith('/')) return [join(target, 'index.html')];

  const out = [target];
  if (!extname(decoded)) {
    out.push(join(target, 'index.html'), `${target}.html`);
  }
  return out;
}
