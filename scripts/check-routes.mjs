/**
 * Lightweight route/link integrity check.
 *
 * 1. Every href in NAV_ITEMS must map to a real app route.
 * 2. Key content routes that are intentionally outside the nav
 *    (currently /metodologia) must be discoverable: at least one
 *    inbound link from another page or component.
 * 3. Every href='/api/...' in app/components must map to a real
 *    app/api proxy (route.ts, honouring [dynamic] segments):
 *    dead buttons against a backend that does not exist fail CI.
 *
 * Runs in CI (npm run test:routes) — no browser needed.
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const root = process.cwd();
const failures = [];

// --- 1. NAV_ITEMS hrefs -> real routes -------------------------------------
const constantsSrc = readFileSync(join(root, 'lib/constants.ts'), 'utf8');
const navHrefs = [...constantsSrc.matchAll(/href:\s*'([^']+)'/g)].map((m) => m[1]);

// Los route groups no son solo (root): la landing publica vive en (public).
// Una ruta existe si su page.tsx esta en CUALQUIER grupo o sin grupo.
const routeGroups = readdirSync(join(root, 'app')).filter(
  (entry) => entry.startsWith('(') && entry.endsWith(')'),
);

function routeExists(href) {
  const segment = href.replace(/^\//, '');
  if (href === '/') {
    return (
      routeGroups.some((group) => existsSync(join(root, 'app', group, 'page.tsx'))) ||
      existsSync(join(root, 'app', 'page.tsx'))
    );
  }
  return (
    routeGroups.some((group) => existsSync(join(root, 'app', group, segment, 'page.tsx'))) ||
    existsSync(join(root, 'app', segment, 'page.tsx'))
  );
}

for (const href of navHrefs) {
  if (!routeExists(href)) failures.push(`NAV_ITEMS links to ${href} but no page exists for that route`);
}

// --- 2. Non-nav routes must be discoverable --------------------------------
const OFF_NAV_ROUTES = ['/metodologia'];

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry.startsWith('.')) continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) yield* walk(full);
    else if (/\.(tsx|ts)$/.test(entry)) yield full;
  }
}

const sources = [
  ...walk(join(root, 'app')),
  ...walk(join(root, 'components')),
].map((file) => [file, readFileSync(file, 'utf8')]);

for (const route of OFF_NAV_ROUTES) {
  // La propia pagina puede vivir en cualquier route group ((root), (public)...):
  // un enlace a si misma no cuenta como inbound en ninguna de ellas.
  const ownPages = new Set(
    routeGroups
      .map((group) => join(root, 'app', group, route.replace(/^\//, ''), 'page.tsx'))
      .concat([join(root, 'app', route.replace(/^\//, ''), 'page.tsx')]),
  );
  const inbound = sources.filter(([file, content]) => !ownPages.has(file) && content.includes(`href="${route}"`));
  if (inbound.length === 0) {
    failures.push(`${route} has no inbound links — it is unreachable in the UI (add a contextual link or remove the route)`);
  }
}

if (failures.length) {
  console.error('Route/link check failed:');
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}

// --- 3. href='/api/...' -> real app/api proxy --------------------------------
const apiRouteFiles = [...walk(join(root, 'app/api'))].filter((file) =>
  file.endsWith('route.ts'),
);
const apiPatterns = apiRouteFiles.map((file) =>
  ['api',
    ...file
      .slice(join(root, 'app/api').length)
    .replace(/\\/g, '/')
    .replace(/\/route\.ts$/, '')
      .split('/')
      .filter(Boolean)],
);

const apiHrefPattern = /href=[{]?[`'"]([/]api[^`'"]+)[`'"][}]?/g;
let apiHrefCount = 0;
for (const [file, content] of sources) {
  for (const match of content.matchAll(apiHrefPattern)) {
    // '/api/thesis/${encoded}/epub' -> '/api/thesis/*/epub': dynamic parts
    // match any [param] segment of the proxy route.
    // La query/hash no forma parte de la ruta ('/pdf?draft=1' -> '/pdf').
    const pathOnly = match[1].split(/[?#]/)[0];
    const normalized = pathOnly.split('${').join('*').split('}').join('');
    apiHrefCount += 1;
    const segments = normalized.split('/').filter(Boolean);
    const matches = apiPatterns.some((pattern) => {
      const catchAll = pattern.findIndex((seg) => seg.startsWith('[...'));
      if (catchAll !== -1) {
        if (segments.length < catchAll) return false;
        return pattern
          .slice(0, catchAll)
          .every(
            (seg, i) =>
              seg.startsWith('[') || seg === '*' || seg === segments[i],
          );
      }
      if (pattern.length !== segments.length) return false;
      return pattern.every(
        (seg, i) =>
          seg.startsWith('[') || segments[i] === '*' || seg === segments[i],
      );
    });
    if (!matches) {
      failures.push(
        `${file} links to ${match[1]} but no app/api proxy route.ts serves that path`,
      );
    }
  }
}

if (failures.length) {
  console.error('Route/link check failed:');
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}
console.log(
  `Route/link check OK: ${navHrefs.length} nav routes resolve, off-nav routes are discoverable, ${apiHrefCount} /api hrefs resolve to app/api proxies.`,
);
