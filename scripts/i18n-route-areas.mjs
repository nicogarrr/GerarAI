/**
 * Áreas del diccionario castellano que necesita cada ruta en el NAVEGADOR.
 *
 * El navegador ya no recibe el castellano entero en el chunk común: lleva las
 * áreas básicas (CORE_AREAS) y descarga el resto por área según la ruta
 * (lib/i18n/messages/es.browser.ts). Este script recorre, para cada
 * app/<ruta>/page.tsx, el grafo de imports de la página y de todos sus layouts
 * (server y client, incluidos los import() dinámicos) y recoge cada literal
 * que empieza por «<área>.» (claves de t(), mapas de claves, prefijos de
 * plantilla `portfolio.zones.${z}`). Es una sobreaproximación a propósito: una
 * área de más solo cuesta bytes; una de menos dejaría un texto sin cargar.
 *
 * Escribe lib/i18n/route-areas.generated.ts (lo ejecuta `npm run prebuild`, así
 * que un build de producción nunca lleva un mapa viejo) y
 * tests/unit/lib/i18n-route-areas.test.ts comprueba que el mapa guardado cubre
 * lo que pide cada ruta hoy.
 */
import { existsSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, normalize, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = normalize(join(dirname(fileURLToPath(import.meta.url)), '..'));
const APP = join(ROOT, 'app');
const MESSAGES_ES = join(ROOT, 'lib/i18n/messages/es');
const I18N_DIR = join(ROOT, 'lib/i18n') + sep;
const OUT = join(ROOT, 'lib/i18n/route-areas.generated.ts');

/** Áreas que van siempre en el chunk común del navegador (las usa el shell). */
export const CORE_AREAS = ['common', 'errors', 'nav', 'search', 'shell', 'ui'];

const EXTS = ['.tsx', '.ts', '.jsx', '.js', '.mjs'];
const SPECIAL = ['layout', 'template', 'loading', 'error', 'not-found', 'forbidden', 'unauthorized', 'default'];
const ASSET = /\.(css|scss|svg|png|jpe?g|gif|webp|avif|ico|woff2?|ttf|md|txt|json)$/;

export function listAreas() {
  return readdirSync(MESSAGES_ES).filter((f) => f.endsWith('.json')).map((f) => f.slice(0, -5)).sort();
}

function resolveSpecifier(spec, from) {
  let base;
  if (spec.startsWith('@/')) base = join(ROOT, spec.slice(2));
  else if (spec.startsWith('./') || spec.startsWith('../')) base = normalize(join(dirname(from), spec));
  else return { external: true };
  if (ASSET.test(base)) return { asset: true };
  const candidates = [base, ...EXTS.map((e) => base + e), ...EXTS.map((e) => join(base, 'index' + e))];
  for (const c of candidates) if (existsSync(c) && statSync(c).isFile()) return { file: c };
  return { unresolved: true };
}

// import x from '…' · import '…' · export … from '…' · import('…') · require('…')
const IMPORT_RE = /\b(?:import|export)\s+(?:type\s+)?(?:[\w*$\s{},]*?\s*from\s*)?['"]([^'"\n]+)['"]|\bimport\s*\(\s*['"]([^'"\n]+)['"]\s*\)|\brequire\s*\(\s*['"]([^'"\n]+)['"]\s*\)/g;

const DIRECTIVE_RE = /^(?:\s|\/\/[^\n]*\n|\/\*[\s\S]*?\*\/)*['"]use (client|server)['"]/;

/**
 * Recorre el grafo con dos modos. En un módulo que puede ir al navegador
 * («use client» y todo lo que importa) cuenta cada literal de clave. En un
 * server component no cuentan las claves que se traducen allí mismo
 * (`t('landing.shell.skipLink')` sale ya como texto en el HTML/RSC), pero sí
 * cualquier otra aparición (mapas de claves, props), que podría acabar en un
 * client component.
 */
export function createAnalyzer(areas = listAreas()) {
  const areaGroup = `(${areas.join('|')})`;
  const literal = new RegExp(`["'\`]${areaGroup}\\.[A-Za-z_]`, 'g');
  const translated = new RegExp(`\\b(?:t|ti|tr)\\(\\s*["'\`]${areaGroup}\\.[A-Za-z_]`, 'g');
  const cache = new Map();
  const unresolved = [];
  function moduleInfo(file) {
    let info = cache.get(file);
    if (info) return info;
    const source = readFileSync(file, 'utf8');
    const deps = [];
    for (const m of source.matchAll(IMPORT_RE)) {
      if (/^(?:import|export)\s+type\s/.test(m[0])) continue;
      const spec = m[1] ?? m[2] ?? m[3];
      const r = resolveSpecifier(spec, file);
      if (r.file) {
        if (!r.file.startsWith(I18N_DIR)) deps.push(r.file);
      } else if (r.unresolved) unresolved.push(`${relative(ROOT, file)} -> ${spec}`);
    }
    const all = new Map();
    const inI18n = file.startsWith(I18N_DIR);
    if (!inI18n) for (const m of source.matchAll(literal)) all.set(m[1], (all.get(m[1]) ?? 0) + 1);
    const serverOnly = new Map(all);
    if (!inI18n) for (const m of source.matchAll(translated)) serverOnly.set(m[1], serverOnly.get(m[1]) - 1);
    const directive = DIRECTIVE_RE.exec(source)?.[1] ?? null;
    info = {
      deps,
      directive,
      client: new Set(all.keys()),
      server: new Set([...serverOnly].filter(([, n]) => n > 0).map(([a]) => a)),
    };
    cache.set(file, info);
    return info;
  }
  function areasOf(entries) {
    const seen = new Set();
    const stack = entries.map((f) => [f, 'server']);
    const result = new Set();
    while (stack.length) {
      let [f, mode] = stack.pop();
      const info = moduleInfo(f);
      if (info.directive === 'client') mode = 'client';
      else if (info.directive === 'server') mode = 'server';
      const key = mode + ':' + f;
      if (seen.has(key)) continue;
      seen.add(key);
      for (const a of info[mode]) result.add(a);
      for (const d of info.deps) stack.push([d, mode]);
    }
    return result;
  }
  return { areasOf, unresolved };
}

function specialFiles(dir) {
  const out = [];
  for (const name of SPECIAL) for (const e of EXTS) {
    const f = join(dir, name + e);
    if (existsSync(f)) out.push(f);
  }
  return out;
}

function findPages(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, entry.name);
    if (entry.isDirectory()) findPages(p, out);
    else if (/^page\.(tsx|ts|jsx|js)$/.test(entry.name)) out.push(p);
  }
  return out;
}

/** «app/(root)/research/[ticker]/page.tsx» -> «/research/[ticker]». */
export function routePattern(pageFile) {
  const segments = relative(APP, dirname(pageFile)).split(sep).filter(Boolean)
    .filter((s) => !(s.startsWith('(') && s.endsWith(')')) && !s.startsWith('@'));
  return '/' + segments.join('/');
}

/** Entradas de una ruta: la página, sus layouts/loading/error y los globales. */
function routeEntries(pageFile) {
  const entries = [pageFile];
  let dir = dirname(pageFile);
  for (;;) {
    entries.push(...specialFiles(dir));
    if (dir === APP) break;
    dir = dirname(dir);
  }
  for (const e of EXTS) {
    const f = join(APP, 'global-error' + e);
    if (existsSync(f)) entries.push(f);
  }
  return entries;
}

/** { '/inicio': ['alerts', ...] } con las áreas NO básicas que pide cada ruta. */
export function computeRouteAreas() {
  const analyzer = createAnalyzer();
  const routes = {};
  for (const page of findPages(APP).sort()) {
    const pattern = routePattern(page);
    const found = analyzer.areasOf(routeEntries(page));
    const prev = new Set(routes[pattern] ?? []);
    for (const a of found) if (!CORE_AREAS.includes(a)) prev.add(a);
    routes[pattern] = [...prev].sort();
  }
  const notFound = analyzer.areasOf(specialFiles(APP));
  return {
    routes,
    notFound: [...notFound].filter((a) => !CORE_AREAS.includes(a)).sort(),
    unresolved: [...new Set(analyzer.unresolved)].sort(),
  };
}

export function renderGenerated({ routes, notFound }) {
  const body = Object.keys(routes).sort().map((r) => `  ${JSON.stringify(r)}: ${JSON.stringify(routes[r])},`).join('\n');
  return `// GENERADO por scripts/i18n-route-areas.mjs (corre en \`npm run prebuild\`). No editar a mano.
// Áreas del castellano que el navegador carga para cada ruta, además de CORE_AREAS.

/** Áreas que lleva siempre el chunk común del navegador. */
export const CORE_AREAS = ${JSON.stringify(CORE_AREAS)} as const;

/** Áreas extra de la página de «no encontrado» (rutas que no casan con ninguna). */
export const NOT_FOUND_AREAS: readonly string[] = ${JSON.stringify(notFound)};

/** Patrón de ruta (como en app/, sin grupos) -> áreas extra que pide. */
export const ROUTE_AREAS: Readonly<Record<string, readonly string[]>> = {
${body}
};
`;
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  const result = computeRouteAreas();
  writeFileSync(OUT, renderGenerated(result));
  if (process.argv.includes('--verbose')) {
    for (const [r, a] of Object.entries(result.routes)) console.log(r, a.join(','));
    if (result.unresolved.length) console.log('unresolved:', result.unresolved);
  }
}
