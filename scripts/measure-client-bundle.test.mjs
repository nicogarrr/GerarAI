/**
 * scripts/measure-client-bundle.mjs: el parser del client-reference-manifest.
 *
 * Con Next 16 (Turbopack) el manifest lista los chunks como URL pública
 * (`/_next/static/chunks/a.js`) y el script los buscaba como
 * `static/chunks/a.js`: ninguno casaba y TODAS las rutas salían con 0 B, en
 * verde y sin avisar. Estas pruebas fijan los dos formatos.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { normalizeChunkPath, routeClientFromManifest } from './measure-client-bundle.mjs';

const manifest = (clientModules) =>
  'globalThis.__RSC_MANIFEST = globalThis.__RSC_MANIFEST || {};\n' +
  `globalThis.__RSC_MANIFEST["/(root)/inicio/page"] = {"moduleLoading":{"prefix":""},"clientModules":${JSON.stringify(clientModules)},"entryJSFiles":{}};`;

test('normaliza la URL pública de Next 16 a la ruta relativa a .next', () => {
  assert.equal(normalizeChunkPath('/_next/static/chunks/a.js'), 'static/chunks/a.js');
  assert.equal(normalizeChunkPath('_next/static/chunks/a.js'), 'static/chunks/a.js');
  assert.equal(normalizeChunkPath('static/chunks/a.js'), 'static/chunks/a.js');
  assert.equal(normalizeChunkPath('/static/chunks/a.js'), 'static/chunks/a.js');
});

test('Next 16: chunks como URL pública, unión sin duplicados y módulos del repo', () => {
  const raw = manifest({
    '[project]/node_modules/next/dist/esm/client/components/layout-router.js': { id: 1, name: '*', chunks: ['/_next/static/chunks/a.js', '/_next/static/chunks/b.js'], async: false },
    '[project]/components/portfolio/PortfolioTabs.tsx <module evaluation>': { id: 2, name: '*', chunks: ['/_next/static/chunks/b.js', '/_next/static/chunks/c.js'], async: false },
    '[project]/components/ui/card.tsx': { id: 3, name: '*', chunks: [], async: false },
  });
  const { chunkFiles, appModules, allModules } = routeClientFromManifest(raw);
  assert.deepEqual([...chunkFiles].sort(), ['static/chunks/a.js', 'static/chunks/b.js', 'static/chunks/c.js']);
  assert.equal(allModules, 2);
  assert.equal(appModules.size, 2);
});

test('formato anterior: ids numéricos intercalados con rutas relativas', () => {
  const raw = manifest({ '/repo/components/x.tsx': { id: 7, name: '*', chunks: [123, 'static/chunks/x.js', 456, 'static/chunks/y.js'] } });
  assert.deepEqual([...routeClientFromManifest(raw).chunkFiles].sort(), ['static/chunks/x.js', 'static/chunks/y.js']);
});

test('sin clientModules no hay chunks', () => {
  assert.equal(routeClientFromManifest('sin manifest').chunkFiles.size, 0);
});
