/**
 * D2c: mide el JS de cliente REAL emitido por `next build` (no estima).
 *
 * Tres numeros, todos leidos del disco del build:
 *
 *  1. `staticBytes` / `staticChunks`: todo el JS que hay en `.next/static`.
 *     Es la misma metrica que ya vigila `scripts/check-bundle-budget.mjs`, asi
 *     que el delta es comparable con el presupuesto del repo.
 *  2. `routeClientBytes[ruta]`: los bytes de los chunks de cliente que el
 *     client-reference-manifest de esa ruta declara. El manifest lo escribe el
 *     compilador y lista EXACTAMENTE los modulos cliente de la ruta; un modulo
 *     que sale de el es un modulo que el navegador ya no descarga.
 *  3. `clientModuleCount`: cuantos modulos cliente declara cada ruta.
 *
 * Uso: node scripts/measure-client-bundle.mjs [salida.json]
 */
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const NEXT_DIR = path.join(REPO_ROOT, '.next');
const STATIC_DIR = path.join(NEXT_DIR, 'static');
const APP_DIR = path.join(NEXT_DIR, 'server', 'app');

function* walk(dir, filter) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(full, filter);
    else if (!filter || filter(entry.name)) yield full;
  }
}

/**
 * El manifest es JSON con una asignacion global por ruta. Las claves de
 * `clientModules` son rutas ABSOLUTAS de fichero (con `\\` escapados en Windows
 * y el junction de node_modules ya resuelto) y los valores son
 * `{"id":<num>,"name":"*","chunks":[<id>,<ruta>,...]}`. Las entradas con
 * `chunks:[]` son modulos cliente cuyo codigo vive en un chunk compartido que
 * ya aporta otra entrada de la misma ruta, asi que para los BYTES se usa la
 * union de las listas no vacias: esa union es exactamente el JS que la ruta
 * carga en el navegador.
 */
const ENTRY_RE = /"((?:[^"\\]|\\.)*?)":\{"id":\d+,"name":"[^"]*","chunks":\[([^\]]*)\]/g;

/**
 * Ruta de chunk tal y como la indexa `chunkSize` (relativa a `.next`, p. ej.
 * `static/chunks/a.js`). Next 16 (Turbopack) escribe en el manifest la URL
 * pública (`/_next/static/chunks/a.js`); antes escribía `static/chunks/a.js`.
 * Sin normalizar, ningún chunk casaba y cada ruta salía con 0 B.
 */
export function normalizeChunkPath(chunk) {
  return chunk.replace(/^\/?_next\//, '').replace(/^\//, '');
}

/**
 * Chunks y módulos cliente que declara un client-reference-manifest. Devuelve
 * los chunks ya normalizados (ver normalizeChunkPath) y los módulos del repo
 * (los de node_modules no distinguen un cambio de otro).
 */
export function routeClientFromManifest(raw) {
  const start = raw.indexOf('"clientModules":{');
  const rest = start >= 0 ? raw.slice(start + '"clientModules":{'.length) : '';

  const chunkFiles = new Set();
  const appModules = new Set();
  let allModules = 0;
  const re = new RegExp(ENTRY_RE.source, 'g');
  let m;
  while ((m = re.exec(rest)) !== null) {
    const key = m[1];
    const chunks = m[2];
    // Solo se cuentan los modulos del repo, no los internos de next/ (que
    // estan en todas las rutas y no distinguen un cambio de otro).
    if (!key.includes('node_modules')) {
      allModules += 1;
      appModules.add(key);
    }
    if (!chunks || chunks.trim() === '') continue;
    for (const c of chunks.split(',')) {
      const trimmed = c.trim().replace(/^"|"$/g, '');
      // La lista alterna id numerico y ruta de chunk (Next 15) o lleva solo
      // rutas (Next 16); solo nos interesan las rutas (las que no son un
      // entero puro).
      if (trimmed && !/^\d+$/.test(trimmed)) chunkFiles.add(normalizeChunkPath(trimmed));
    }
  }
  return { chunkFiles, appModules, allModules };
}


function main() {
  // 1. Todo el JS emitido
  const jsFiles = [...walk(STATIC_DIR, (n) => n.endsWith('.js'))];
  let staticBytes = 0;
  for (const f of jsFiles) staticBytes += statSync(f).size;

  // tamano por chunk, indexado por la ruta que usan los manifests
  // (`static/chunks/...`), es decir relativa a `.next` y no a `.next/static`.
  const chunkSize = new Map();
  for (const f of jsFiles) {
    const rel = path.relative(NEXT_DIR, f).split(path.sep).join('/');
    chunkSize.set(rel, statSync(f).size);
  }

  // 2 y 3. Por ruta, desde los client-reference-manifest
  const routeClientBytes = {};
  const routeClientModules = {};
  const routeAppClientModules = {};
  const routeChunks = {};

  for (const manifest of walk(APP_DIR, (n) => n.endsWith('client-reference-manifest.js'))) {
    const raw = readFileSync(manifest, 'utf8');
    const route = path
      .relative(APP_DIR, manifest)
      .split(path.sep)
      .join('/')
      .replace(/\/?page_client-reference-manifest\.js$/, '')
      .replace(/client-reference-manifest\.js$/, '');

    const { chunkFiles, appModules, allModules } = routeClientFromManifest(raw);

    let bytes = 0;
    for (const c of chunkFiles) {
      const size = chunkSize.get(c);
      if (size != null) bytes += size;
    }
    routeClientBytes[route] = bytes;
    routeClientModules[route] = allModules;
    routeAppClientModules[route] = appModules.size;
    routeChunks[route] = chunkFiles.size;
  }

  const routes = Object.keys(routeClientBytes).sort();
  const totalRouteBytes = routes.reduce((a, r) => a + routeClientBytes[r], 0);
  const totalAppClientModules = routes.reduce((a, r) => a + routeClientModules[r], 0);
  const avgRouteBytes = routes.length ? totalRouteBytes / routes.length : 0;

  console.log(`staticBytes           ${staticBytes} B (${(staticBytes / 1024).toFixed(1)} kB) en ${jsFiles.length} chunks`);
  console.log(`rutas                 ${routes.length}`);
  console.log(`suma first-load/ruta  ${totalRouteBytes} B (${(totalRouteBytes / 1024).toFixed(1)} kB)`);
  console.log(`media first-load/ruta ${Math.round(avgRouteBytes)} B (${(avgRouteBytes / 1024).toFixed(1)} kB)`);
  console.log(`modulos cliente (app) ${totalAppClientModules} referencias de ruta a modulo`);
  console.log('');
  for (const r of routes.sort((a, b) => routeClientBytes[b] - routeClientBytes[a])) {
    console.log(`  ${String(routeClientBytes[r]).padStart(8)} B  ${String(routeClientModules[r]).padStart(4)} mod  ${r}`);
  }

  const out = process.argv[2];
  if (out) {
    writeFileSync(
      out,
      JSON.stringify(
        { staticBytes, staticChunks: jsFiles.length, totalRouteBytes, avgRouteBytes, totalAppClientModules, routeClientBytes, routeClientModules },
        null,
        2,
      ),
    );
    console.log(`\nescrito ${out}`);
  }
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) main();
