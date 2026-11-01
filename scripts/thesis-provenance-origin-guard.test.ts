import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const memo = readFileSync('components/research/ThesisMemo.tsx', 'utf8');
const groups = readFileSync('lib/research/provenance-groups.ts', 'utf8');
// El filtro https y el veredicto OFICIAL viven en el helper compartido desde
// la refactorizacion del memo; el guard los sigue exigiendo, en su sitio nuevo.
const item = readFileSync('lib/research/provenance-item.ts', 'utf8');

test('inputs are grouped, link only https sources and carry no repeated badge', () => {
  assert.doesNotMatch(memo, />\s*INFERIDO\s*</);
  assert.match(memo, /PROVENANCE_GROUPS\.map/);
  assert.match(item, /\^https:/);
  assert.match(memo, /rel="noopener noreferrer"/);
  assert.match(memo, /break-all text-teal-400 underline|text-teal-400 underline/);
});

test('render is fail-closed: only a verified official source counts as reportado', () => {
  assert.match(item, /export function isVerifiedOficial/);
  assert.match(item, /f\.oficial && !!f\.fecha/);
  assert.match(memo, /isVerifiedOficial\(item\)\) === group\.key/);
  assert.match(groups, /verified \? 'reportado' : 'sin_verificar'/);
  assert.match(memo, /basis \?\? t\('research\.memo\.basisUndocumented'\)/);
  assert.match(readFileSync('lib/i18n/messages/es/research.json', 'utf8'), /"basisUndocumented": "Base no documentada"/);
});

test('basis texts are Spanish', () => {
  assert.doesNotMatch(groups, /'Median of|'Annual/);
  assert.match(groups, /Mediana de los últimos márgenes FCF anuales/);
});

// Visto en prod con AAPL (19-oct-2026): «Reportado, período 2025-09-27:FY»
// enseñaba ISO + sufijo crudo. El periodo se pinta en español natural.
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { periodoEs, provenanceBasisEs } from '../lib/research/provenance-groups.ts';

test('periodo estructurado se pinta en español natural', () => {
  assert.equal(periodoEs('2025-09-27:FY'), 'ejercicio fiscal 2025 (cierre 27 sept 2025)');
  assert.equal(periodoEs('2026-06-30:Q2'), 'T2 2026 (cierre 30 jun 2026)');
  assert.equal(periodoEs('otro-formato'), 'otro-formato');
  assert.equal(provenanceBasisEs('fcf reportado (periodo 2025-09-27:FY)'), 'Reportado, ejercicio fiscal 2025 (cierre 27 sept 2025)');
  assert.equal(provenanceBasisEs('fcf reportado'), 'Reportado');
});
