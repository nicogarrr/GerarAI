/**
 * Áreas del castellano que necesita una ruta en el navegador, además de las
 * básicas que lleva el chunk común. El mapa lo genera
 * scripts/i18n-route-areas.mjs a partir del grafo de imports de cada página
 * (ver route-areas.generated.ts); aquí solo se casa la URL con los patrones.
 *
 * Si una URL casa con varios patrones (/research/news y /research/[ticker]) se
 * cargan las áreas de todos; si no casa con ninguno se carga lo de la página
 * «no encontrado». Módulo puro: lo usan el navegador, el servidor y los tests.
 */
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { NOT_FOUND_AREAS, ROUTE_AREAS } from './route-areas.generated.ts';

type Matcher = { regex: RegExp; areas: readonly string[] };

function escapeRegex(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** «/research/[ticker]» -> /^\/research\/[^/]+$/ ; [...x] y [[...x]] casan varios segmentos. */
export function routePatternRegex(pattern: string): RegExp {
  if (pattern === '/') return /^\/$/;
  let source = '';
  for (const segment of pattern.split('/').filter(Boolean)) {
    if (/^\[\[\.\.\..+\]\]$/.test(segment)) source += '(?:/.*)?';
    else if (/^\[\.\.\..+\]$/.test(segment)) source += '/.+';
    else if (/^\[.+\]$/.test(segment)) source += '/[^/]+';
    else source += '/' + escapeRegex(segment);
  }
  return new RegExp(`^${source}$`);
}

const MATCHERS: Matcher[] = Object.entries(ROUTE_AREAS as Record<string, readonly string[]>).map(([pattern, areas]) => ({
  regex: routePatternRegex(pattern),
  areas,
}));

const cache = new Map<string, readonly string[]>();

/** Áreas extra (no básicas) que pide la URL `pathname` en el navegador. */
export function spanishAreasForPath(pathname: string | null | undefined): readonly string[] {
  let path = (pathname || '/').split(/[?#]/)[0];
  if (path.length > 1 && path.endsWith('/')) path = path.slice(0, -1);
  let decoded = path;
  try { decoded = decodeURI(path); } catch { /* URL mal formada: se casa tal cual */ }
  const cached = cache.get(decoded);
  if (cached) return cached;
  const result = new Set<string>();
  let matched = false;
  for (const { regex, areas } of MATCHERS) {
    if (!regex.test(decoded)) continue;
    matched = true;
    for (const area of areas) result.add(area);
  }
  if (!matched) for (const area of NOT_FOUND_AREAS as readonly string[]) result.add(area);
  const areas = [...result].sort();
  if (cache.size > 200) cache.clear();
  cache.set(decoded, areas);
  return areas;
}
