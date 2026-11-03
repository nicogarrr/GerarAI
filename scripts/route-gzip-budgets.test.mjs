/**
 * Guard de presupuestos gzip por ruta (ver scripts/check-route-gzip-budgets.mjs).
 *
 * Las pruebas del parser corren siempre (un parser que devuelve 0 B daría
 * verde a todo: le pasaba a measure-client-bundle.mjs con el formato de
 * manifest de Next 16). La medición real solo corre si hay un build de
 * producción (`.next/BUILD_ID`); sin build se marca como omitida.
 */
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';

import {
  KB,
  ROUTE_GZIP_BUDGETS_KB,
  check,
  entryChunksFromManifest,
  gzipBytes,
  measure,
} from './check-route-gzip-budgets.mjs';

const manifest = (entries) =>
  'globalThis.__RSC_MANIFEST = globalThis.__RSC_MANIFEST || {};\n' +
  `globalThis.__RSC_MANIFEST["/(root)/inicio/page"] = {"moduleLoading":{"prefix":""},"clientModules":{"x":{"id":1,"name":"*","chunks":["/_next/static/chunks/a.js"],"async":false}},"entryJSFiles":${JSON.stringify(entries)},"entryCSSFiles":{}};`;

test('el parser lee los chunks de primera carga de la página, no los de otra entrada', () => {
  const raw = manifest({
    '[project]/app/layout': ['static/chunks/a.js'],
    '[project]/app/(root)/inicio/page': ['static/chunks/a.js', 'static/chunks/b.js'],
    '[project]/app/(root)/error': ['static/chunks/z.js'],
  });
  assert.deepEqual(entryChunksFromManifest(raw, '(root)/inicio'), ['static/chunks/a.js', 'static/chunks/b.js']);
  assert.deepEqual(entryChunksFromManifest(raw, '(root)/portfolio'), []);
  assert.deepEqual(entryChunksFromManifest('sin manifest', '(root)/inicio'), []);
});

test('la portada (ruta de grupo sin segmento) usa la clave del grupo', () => {
  const raw = manifest({ '[project]/app/(public)/page': ['static/chunks/p.js'] });
  assert.deepEqual(entryChunksFromManifest(raw, '(public)'), ['static/chunks/p.js']);
});

test('check falla cerrado: ruta por encima del presupuesto o ruta que falta', () => {
  const sizes = { framework: 100 * KB, '(root)/inicio': 300 * KB };
  const { failures } = check({ sizes, missing: ['(root)/portfolio: no hay manifest'] }, { framework: 120, '(root)/inicio': 250 });
  assert.equal(failures.length, 2);
  assert.match(failures[0], /portfolio/);
  assert.match(failures[1], /inicio: 300\.0 KB gzip > presupuesto 250 KB/);
  assert.deepEqual(check({ sizes, missing: [] }, { framework: 120, '(root)/inicio': 300 }).failures, []);
});

test('gzip nivel 6 comprime de verdad (los presupuestos son bytes comprimidos)', () => {
  const raw = Buffer.from('export const x = 1;\n'.repeat(500));
  assert.ok(gzipBytes(raw) < raw.length / 10);
});

test('presupuestos declarados para las rutas clave', () => {
  for (const route of ['framework', '(root)/inicio', '(root)/portfolio', '(root)/research/[ticker]', '(root)/watchlist']) {
    assert.ok(ROUTE_GZIP_BUDGETS_KB[route] > 0, `falta presupuesto para ${route}`);
  }
});

const nextDir = path.resolve('.next');
const hasBuild = existsSync(path.join(nextDir, 'BUILD_ID'));

test('el JS de primera carga de cada ruta clave cabe en su presupuesto gzip', { skip: hasBuild ? false : 'sin build de producción (npm run build)' }, () => {
  const measured = measure(nextDir);
  const { rows, failures } = check(measured);
  assert.deepEqual(failures, [], rows.map((r) => `${r.route} ${r.kb.toFixed(1)}/${r.budgetKb} KB`).join('\n'));
  assert.equal(rows.length, Object.keys(ROUTE_GZIP_BUDGETS_KB).length);
});
