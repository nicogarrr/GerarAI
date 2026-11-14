/**
 * Bundle report por ruta (informativo, NUNCA rompe CI).
 *
 * `next build` ya no imprime la tabla "First Load JS" en el log de CI, así que
 * no hay medición por ruta para auditar presupuesto de JS. Este script la
 * reconstruye a partir de lo que haya emitido el build:
 *
 *   1. .next/diagnostics/route-bundle-stats.json -> First Load JS por ruta,
 *      calculado por el propio `next build` (solo builds Turbopack)
 *   2. .next/app-build-manifest.json  -> chunks por ruta del App Router (webpack)
 *   3. .next/build-manifest.json      -> pages{} + rootMainFiles (webpack)
 *   4. .next/static/chunks/app/**     -> rutas inferidas del nombre de chunk
 *      (estimación: el chunk de una ruta puede no ser toda su carga inicial)
 *
 * Si ninguna fuente existe, escribe informe explícito de "sin datos" y sale 0.
 * Cualquier error interno (manifest con forma inesperada, fs, etc.) se atrapa
 * y también sale 0: el presupuesto que rompe CI vive en check-bundle-budget.mjs.
 *
 * Salida:
 *   - JSON con el detalle completo (--json, por defecto bundle-report.json)
 *   - Markdown con la tabla por ruta (--markdown, por defecto bundle-report.md)
 *
 * La columna gzip aproxima el tamaño transferido (gzip -9; Caddy puede servir
 * brotli, ligeramente menor). Los chunks compartidos se contabilizan en cada
 * ruta: es el coste de primera carga real de esa ruta.
 */
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve, sep } from 'node:path';
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';

const ROOT = resolve(fileURLToPath(new URL('..', import.meta.url)));

function argValue(flag, fallback) {
  const i = process.argv.indexOf(flag);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const NEXT_DIR = resolve(ROOT, argValue('--dir', '.next'));
const JSON_OUT = resolve(ROOT, argValue('--json', 'bundle-report.json'));
const MD_OUT = resolve(ROOT, argValue('--markdown', 'bundle-report.md'));

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch {
    return null;
  }
}

function fileStats(relPath) {
  // Los manifests referencian "static/chunks/..." (relativo a .next) o
  // "/_next/static/..." (URL pública). Normalizamos ambas formas.
  const rel = String(relPath).replace(/^[\\/]*_next[\\/]/, '');
  const abs = resolve(NEXT_DIR, rel);
  if (!abs.startsWith(NEXT_DIR + sep) || !existsSync(abs)) return null;
  try {
    const content = readFileSync(abs);
    return { raw: content.length, gzip: gzipSync(content, { level: 9 }).length };
  } catch {
    return null;
  }
}

/** "/(root)/inicio/page" -> "/inicio"; "/(public)/page" -> "/". */
function normalizeRoute(pageKey) {
  const segments = String(pageKey)
    .split('/')
    .filter((s) => s && !s.startsWith('(') && !s.startsWith('@'));
  if (segments.length > 0 && /^(page|route|layout|loading|default)$/.test(segments[segments.length - 1])) {
    segments.pop();
  }
  return '/' + segments.join('/');
}

function emptyReport(reason) {
  return {
    generatedAt: new Date().toISOString(),
    source: null,
    note: reason,
    shared: { files: [], raw: 0, gzip: 0 },
    middleware: null,
    routes: [],
    largestChunks: [],
  };
}

/** Fuente 1: route-bundle-stats.json que escribe el propio `next build` con Turbopack. */
function reportFromRouteBundleStats() {
  const rows = readJson(join(NEXT_DIR, 'diagnostics', 'route-bundle-stats.json'));
  if (!Array.isArray(rows) || rows.length === 0) return null;
  const routes = [];
  let missingTotal = 0;
  for (const row of rows) {
    if (!row || typeof row.route !== 'string' || !Array.isArray(row.firstLoadChunkPaths)) continue;
    let gzip = 0;
    let missingChunks = 0;
    const chunks = [];
    for (const p of row.firstLoadChunkPaths) {
      // Las rutas vienen relativas al repo (".next/static/...").
      const rel = String(p).replace(/^[./]*\.next[\/]/, '');
      const s = fileStats(rel);
      if (!s) {
        missingChunks += 1;
        continue;
      }
      chunks.push(rel);
      gzip += s.gzip;
    }
    missingTotal += missingChunks;
    // raw conserva el total que calculó Next (incluye chunks ausentes);
    // gz solo suma los chunks encontrados: si missingChunks > 0, el gz queda
    // por debajo del real y la ruta se marca con † en la tabla.
    const raw = typeof row.firstLoadUncompressedJsBytes === 'number' ? row.firstLoadUncompressedJsBytes : 0;
    // route verbatim: Next ya entrega la ruta normalizada (normalizeAppPath);
    // entradas como /loading, /default o /page son filas distintas y no
    // deben fundirse aplicando normalizeRoute otra vez.
    routes.push({ route: row.route, page: row.route, raw, gzip, routeChunks: chunks, missingChunks });
  }
  if (routes.length === 0) return null;
  routes.sort((a, b) => b.raw - a.raw);
  return { routes, shared: { files: [], raw: 0, gzip: 0 }, largestChunks: buildLargestChunks(routes), missingTotal };
}

function buildLargestChunks(routes) {
  const chunkRoutes = new Map();
  for (const r of routes) {
    for (const f of r.routeChunks) {
      if (!chunkRoutes.has(f)) chunkRoutes.set(f, []);
      chunkRoutes.get(f).push(r.route);
    }
  }
  return [...chunkRoutes.keys()]
    .map((f) => ({ file: f, ...(fileStats(f) ?? { raw: 0, gzip: 0 }), routes: chunkRoutes.get(f) ?? [] }))
    .sort((a, b) => b.raw - a.raw)
    .slice(0, 10);
}

/** Fuentes 2 y 3: manifest con mapa de páginas -> chunks. */
function reportFromManifest(pages, rootMainFiles, source) {
  const sharedSet = new Set(Array.isArray(rootMainFiles) ? rootMainFiles : []);
  const shared = { files: [], raw: 0, gzip: 0 };
  for (const f of sharedSet) {
    const s = fileStats(f);
    if (!s) continue;
    shared.files.push(f);
    shared.raw += s.raw;
    shared.gzip += s.gzip;
  }

  // Estadísticas por chunk, cacheadas: el mismo chunk aparece en muchas rutas.
  const chunkStats = new Map();
  const statsFor = (f) => {
    if (!chunkStats.has(f)) chunkStats.set(f, fileStats(f) ?? { raw: 0, gzip: 0 });
    return chunkStats.get(f);
  };

  const routes = [];
  for (const [page, chunks] of Object.entries(pages)) {
    if (!Array.isArray(chunks)) continue;
    const routeChunks = [...new Set(chunks.filter((f) => typeof f === 'string' && !sharedSet.has(f)))];
    let raw = shared.raw;
    let gzip = shared.gzip;
    for (const f of routeChunks) {
      const s = statsFor(f);
      raw += s.raw;
      gzip += s.gzip;
    }
    routes.push({ route: normalizeRoute(page), page, raw, gzip, routeChunks });
  }
  routes.sort((a, b) => b.raw - a.raw);

  const chunkRoutes = new Map();
  for (const r of routes) {
    for (const f of [...r.routeChunks, ...shared.files]) {
      if (!chunkRoutes.has(f)) chunkRoutes.set(f, []);
      chunkRoutes.get(f).push(r.route);
    }
  }
  const allChunkFiles = new Set();
  for (const chunks of Object.values(pages)) {
    if (Array.isArray(chunks)) for (const f of chunks) if (typeof f === 'string') allChunkFiles.add(f);
  }
  const largestChunks = [...allChunkFiles]
    .map((f) => ({ file: f, ...statsFor(f), routes: chunkRoutes.get(f) ?? [] }))
    .sort((a, b) => b.raw - a.raw)
    .slice(0, 10);

  return { source, routes, shared, largestChunks };
}

/** Fuente 3 (estimación): infiere rutas de .next/static/chunks/app/<ruta>/*.js. */
function reportFromChunkTree() {
  const appDir = join(NEXT_DIR, 'static', 'chunks', 'app');
  if (!existsSync(appDir)) return null;
  const routes = [];
  const walk = (dir, parts) => {
    let raw = 0;
    let gzip = 0;
    const files = [];
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(p, [...parts, entry.name]);
      } else if (entry.name.endsWith('.js')) {
        const rel = p.slice(NEXT_DIR.length + 1);
        const s = fileStats(rel);
        if (!s) continue;
        files.push(rel);
        raw += s.raw;
        gzip += s.gzip;
      }
    }
    if (files.length > 0) {
      routes.push({ route: normalizeRoute(parts.join('/') || 'page'), page: parts.join('/'), raw, gzip, routeChunks: files });
    }
  };
  walk(appDir, []);
  if (routes.length === 0) return null;
  routes.sort((a, b) => b.raw - a.raw);
  const largestChunks = routes
    .flatMap((r) => r.routeChunks.map((f) => ({ file: f, ...(fileStats(f) ?? { raw: 0, gzip: 0 }), routes: [r.route] })))
    .sort((a, b) => b.raw - a.raw)
    .slice(0, 10);
  return {
    source: 'chunk-tree',
    routes,
    shared: { files: [], raw: 0, gzip: 0 },
    largestChunks,
  };
}

function middlewareStats() {
  // Webpack: bundle único. Turbopack: lista de files en middleware-manifest.
  const mwPath = join(NEXT_DIR, 'server', 'middleware.js');
  if (existsSync(mwPath)) {
    try {
      const content = readFileSync(mwPath);
      return { raw: content.length, gzip: gzipSync(content, { level: 9 }).length };
    } catch {
      return null;
    }
  }
  const manifest = readJson(join(NEXT_DIR, 'server', 'middleware-manifest.json'));
  const files = manifest?.middleware?.['/']?.files;
  if (!Array.isArray(files) || files.length === 0) return null;
  let raw = 0;
  let gzip = 0;
  for (const f of files) {
    // Los paths del middleware-manifest ya son relativos a .next ("server/...").
    const s = fileStats(f);
    if (!s) continue;
    raw += s.raw;
    gzip += s.gzip;
  }
  return raw > 0 ? { raw, gzip } : null;
}

function writeOutputs(report) {
  const kb = (n) => (n / 1024).toFixed(1);
  const lines = [
    '## Bundle report por ruta (JS inicial, App Router)',
    '',
    `> ${report.note}`,
    report.source ? `> Fuente: ${report.source}` : null,
    '',
    report.source === 'route-bundle-stats'
      ? 'Compartido: ya incluido en el total de cada ruta (First Load JS calculado por el build).'
      : `Compartido (rootMainFiles): **${kb(report.shared.raw)} KB** raw / ${kb(report.shared.gzip)} KB gz en ${report.shared.files.length} chunks.`,
    report.middleware
      ? `Middleware: **${kb(report.middleware.raw)} KB** raw / ${kb(report.middleware.gzip)} KB gz.`
      : 'Middleware: no encontrado en el build.',
    '',
    '| Ruta | JS inicial raw (KB) | JS inicial gz (KB) | Chunks ruta |',
    '| --- | ---: | ---: | ---: |',
    ...report.routes.map(
      (r) => `| \`${r.route}\`${r.missingChunks > 0 ? ' †' : ''} | ${kb(r.raw)} | ${kb(r.gzip)} | ${r.routeChunks.length} |`,
    ),
    ...(report.routes.some((r) => (r.missingChunks ?? 0) > 0)
      ? ['', '† gz parcial: hay chunks referenciados ausentes en disco; el raw es el total del build y el gz solo suma los chunks encontrados.']
      : []),
    '',
    '### 10 chunks más grandes del build',
    '',
    '| Chunk | raw (KB) | gz (KB) | Rutas que lo cargan |',
    '| --- | ---: | ---: | --- |',
    ...report.largestChunks.map(
      (c) => `| \`${c.file}\` | ${kb(c.raw)} | ${kb(c.gzip)} | ${c.routes.length > 0 ? c.routes.map((r) => `\`${r}\``).join(', ') : '_(lazy, fuera de carga inicial)_'} |`,
    ),
  ].filter((l) => l !== null);
  const md = lines.join('\n') + '\n';
  try {
    for (const out of [JSON_OUT, MD_OUT]) mkdirSync(dirname(out), { recursive: true });
    writeFileSync(JSON_OUT, JSON.stringify(report, null, 2));
    writeFileSync(MD_OUT, md);
  } catch (err) {
    console.warn(`bundle-report: no pude escribir el informe (${err?.message ?? err}); continuo sin artefacto.`);
  }
  return lines;
}

function main() {
  const appManifest = readJson(join(NEXT_DIR, 'app-build-manifest.json'));
  const buildManifest = readJson(join(NEXT_DIR, 'build-manifest.json'));

  let report;
  const fromStats = reportFromRouteBundleStats();
  if (fromStats) {
    report = {
      generatedAt: new Date().toISOString(),
      source: 'route-bundle-stats',
      note:
        'First Load JS por ruta calculado por el propio `next build` (diagnostics/route-bundle-stats.json); la columna gz se añade aquí con gzip -9 como aproximación del tamaño transferido. Los chunks compartidos ya van incluidos en cada ruta.' +
        (fromStats.missingTotal > 0
          ? ` OJO: ${fromStats.missingTotal} chunk(s) referenciados no están en disco; en las rutas marcadas con † el raw es el total del build pero el gz es parcial.`
          : ''),
      shared: fromStats.shared,
      middleware: middlewareStats(),
      routes: fromStats.routes,
      largestChunks: fromStats.largestChunks,
      missingChunks: fromStats.missingTotal,
    };
  } else if (appManifest && appManifest.pages && typeof appManifest.pages === 'object') {
    const partial = reportFromManifest(
      appManifest.pages,
      appManifest.rootMainFiles ?? buildManifest?.rootMainFiles,
      'app-build-manifest',
    );
    report = {
      generatedAt: new Date().toISOString(),
      source: partial.source,
      note: 'Aproximación: gzip -9 estima el tamaño transferido y los chunks compartidos se contabilizan en cada ruta; los chunks referenciados pero ausentes en disco se omiten del cómputo.',
      shared: partial.shared,
      middleware: middlewareStats(),
      routes: partial.routes,
      largestChunks: partial.largestChunks,
    };
  } else if (buildManifest && buildManifest.pages && typeof buildManifest.pages === 'object') {
    const partial = reportFromManifest(buildManifest.pages, buildManifest.rootMainFiles, 'build-manifest');
    report = {
      generatedAt: new Date().toISOString(),
      source: partial.source,
      note: 'Sin app-build-manifest.json: tabla desde build-manifest (puede mezclar convenciones del Pages Router).',
      shared: partial.shared,
      middleware: middlewareStats(),
      routes: partial.routes,
      largestChunks: partial.largestChunks,
    };
  } else {
    const partial = reportFromChunkTree();
    report = partial
      ? {
          generatedAt: new Date().toISOString(),
          source: partial.source,
          note: 'ESTIMACIÓN sin manifests: rutas inferidas de .next/static/chunks/app/**; los chunks fuera de ese árbol (compartidos, lazy con otro nombre) no se contabilizan, así que los totales pueden quedar por debajo del real.',
          shared: partial.shared,
          middleware: middlewareStats(),
          routes: partial.routes,
          largestChunks: partial.largestChunks,
        }
      : emptyReport('Sin app-build-manifest.json, build-manifest.json ni chunks de app: este build no emite fuente de datos reconocible. Informe vacío, sin error.');
  }

  const lines = writeOutputs(report);
  console.log(`bundle-report: fuente=${report.source ?? 'ninguna'}; ${report.routes.length} rutas; compartido ${(report.shared.gzip / 1024).toFixed(1)} KB gz; informe en ${JSON_OUT} y ${MD_OUT}`);
  console.log(lines.slice(0, 12).join('\n'));
}

try {
  main();
} catch (err) {
  // Informativo: ningún fallo de este script debe romper CI.
  console.warn(`bundle-report: error inesperado (${err?.stack ?? err}); salgo 0 para no bloquear CI.`);
}
process.exit(0);
