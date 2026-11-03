/**
 * Presupuestos gzip del JS de primera carga por ruta (rendimiento-12, 3 nov 2026).
 *
 * Fija lo ganado en las tandas de rendimiento (#4344 sacó el inglés del chunk
 * común: −74 KB gzip por página) para que un import pesado nuevo no lo
 * deshaga sin que nadie lo vea. `check-bundle-budget.mjs` vigila techos
 * gruesos sin comprimir (600 kB por chunk, 12 MB en total); este mide lo que
 * de verdad descarga el navegador al abrir cada ruta clave.
 *
 * Qué mide, leído del disco tras `next build` (Turbopack):
 *  - por ruta: los chunks que `entryJSFiles["[project]/app/<ruta>/page"]` del
 *    client-reference-manifest de esa página declara (layouts incluidos). Es el
 *    "First Load JS" de la ruta SIN el framework común;
 *  - `framework`: los `rootMainFiles` + `polyfillFiles` de build-manifest.json,
 *    comunes a todas las páginas.
 * Cada chunk se comprime con gzip nivel 6 (el de Node y el de Caddy) y se suma,
 * igual que llega por la red.
 *
 * Presupuesto = lo medido en main + ~5 % de margen. Si una mejora baja una ruta,
 * baja aquí su número; si un cambio la sube a propósito, súbelo en el mismo PR
 * diciendo por qué.
 *
 * Uso:  npm run build && node scripts/check-route-gzip-budgets.mjs [--json salida.json]
 * Salida != 0 si alguna ruta pasa su presupuesto o falta en el build (fail closed).
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

export const KB = 1024;

/** KB gzip (nivel 6), medido con `next build` el 3 nov 2026 (main 96237665; re-medido en 7a71c328e). */
export const ROUTE_GZIP_BUDGETS_KB = {
  // medido → presupuesto (KB gzip). Re-medido tras #4432 (castellano por área), main 7a71c328e.
  framework: 177, // 168,5
  '(root)/inicio': 117, // 110,9
  '(root)/portfolio': 128, // 121,6
  '(root)/portfolio/intelligence': 94, // 88,9
  '(root)/research/[ticker]': 162, // 154,2
  '(root)/watchlist': 135, // 128,5
  '(root)/plan': 132, // 125,1
  '(auth)/sign-in': 61, // 57,3
  '(public)': 41, // 38,4 (portada)
};

/**
 * Chunks de primera carga de una ruta a partir del texto del
 * client-reference-manifest. Devuelve [] si la ruta no está.
 */
export function entryChunksFromManifest(raw, route) {
  const marker = '"entryJSFiles":';
  const at = raw.indexOf(marker);
  if (at < 0) return [];
  // entryJSFiles es un objeto JSON plano {clave: [rutas]}; se recorta hasta su llave de cierre.
  let depth = 0;
  let end = -1;
  for (let i = at + marker.length; i < raw.length; i += 1) {
    const ch = raw[i];
    if (ch === '{') depth += 1;
    else if (ch === '}') {
      depth -= 1;
      if (depth === 0) {
        end = i + 1;
        break;
      }
    }
  }
  if (end < 0) return [];
  const entries = JSON.parse(raw.slice(at + marker.length, end));
  const key = `[project]/app/${route ? `${route}/` : ''}page`;
  return Array.isArray(entries[key]) ? entries[key] : [];
}

export function gzipBytes(buffer) {
  return gzipSync(buffer, { level: 6 }).length;
}

export function measure(nextDir) {
  const sizes = {};
  const missing = [];
  const cache = new Map();
  const chunkGzip = (rel) => {
    if (!cache.has(rel)) {
      const file = path.join(nextDir, rel);
      cache.set(rel, existsSync(file) ? gzipBytes(readFileSync(file)) : null);
    }
    return cache.get(rel);
  };
  const sum = (chunks, label) => {
    let total = 0;
    for (const rel of new Set(chunks)) {
      const size = chunkGzip(rel);
      if (size == null) missing.push(`${label}: ${rel}`);
      else total += size;
    }
    return total;
  };

  const buildManifest = JSON.parse(readFileSync(path.join(nextDir, 'build-manifest.json'), 'utf8'));
  const framework = [...(buildManifest.rootMainFiles ?? []), ...(buildManifest.polyfillFiles ?? [])];
  if (framework.length === 0) missing.push('framework: build-manifest.json sin rootMainFiles');
  sizes.framework = sum(framework, 'framework');

  for (const route of Object.keys(ROUTE_GZIP_BUDGETS_KB)) {
    if (route === 'framework') continue;
    const manifest = path.join(nextDir, 'server', 'app', route, 'page_client-reference-manifest.js');
    if (!existsSync(manifest)) {
      missing.push(`${route}: no hay ${path.relative(nextDir, manifest)}`);
      continue;
    }
    const chunks = entryChunksFromManifest(readFileSync(manifest, 'utf8'), route);
    if (chunks.length === 0) {
      missing.push(`${route}: el manifest no declara entryJSFiles para la página`);
      continue;
    }
    sizes[route] = sum(chunks, route);
  }
  return { sizes, missing };
}

export function check({ sizes, missing }, budgets = ROUTE_GZIP_BUDGETS_KB) {
  const failures = [...missing];
  const rows = [];
  for (const [route, budgetKb] of Object.entries(budgets)) {
    const bytes = sizes[route];
    if (bytes == null) continue;
    const kb = bytes / KB;
    const ok = kb <= budgetKb;
    rows.push({ route, kb, budgetKb, ok });
    if (!ok) failures.push(`${route}: ${kb.toFixed(1)} KB gzip > presupuesto ${budgetKb} KB`);
  }
  return { rows, failures };
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  const nextDir = path.join(repoRoot, '.next');
  if (!existsSync(path.join(nextDir, 'BUILD_ID'))) {
    console.error('route-gzip-budgets: no hay build de producción (.next/BUILD_ID). Ejecuta `npm run build` antes.');
    process.exit(1);
  }
  const measured = measure(nextDir);
  const { rows, failures } = check(measured);
  for (const { route, kb, budgetKb, ok } of rows) {
    console.log(`${ok ? 'ok  ' : 'FAIL'} ${kb.toFixed(1).padStart(7)} KB gzip / ${String(budgetKb).padStart(4)} KB  ${route}`);
  }
  const jsonAt = process.argv.indexOf('--json');
  if (jsonAt > 0 && process.argv[jsonAt + 1]) {
    writeFileSync(process.argv[jsonAt + 1], JSON.stringify(measured, null, 2));
  }
  if (failures.length > 0) {
    console.error(`\nroute-gzip-budgets: ${failures.length} fallo(s):`);
    for (const f of failures) console.error(`  - ${f}`);
    process.exit(1);
  }
  console.log('\nroute-gzip-budgets: todas las rutas dentro de presupuesto.');
}
