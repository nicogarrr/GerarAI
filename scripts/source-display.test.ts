import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { sourceDisplay } from '../lib/research/source-display.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { auditFixLabel } from '../lib/audit-status-copy.ts';

test('fuentes conocidas se traducen sin convertir una fuente futura en otra', () => {
  assert.equal(sourceDisplay('primary_official'), 'Fuente oficial primaria');
  assert.equal(sourceDisplay('yahoo_finance_intraday'), 'Yahoo Finance · intradía');
  assert.equal(sourceDisplay('future_provider'), 'future provider');
});

test('bloqueos conocidos y métricas se presentan en español sin cambiar cifras', () => {
  assert.equal(auditFixLabel('No calculation trace -> no valuation.'), 'Sin traza de cálculo no hay valoración: faltan variables de entrada; completa los datos y regenera la tesis.');
  assert.equal(auditFixLabel('Faltan normalized_fcf_or_fcf_margin, shares_diluted (2025).'), 'Faltan FCF normalizado o margen FCF, Acciones diluidas (media) (2025).');
});

test('inventario separa noticias sin paginar fuera los fundamentales', () => {
  const page = readFileSync('app/(root)/research/data-health/page.tsx', 'utf8');
  assert.ok(page.includes("row.layer !== 'Noticias'"));
  assert.ok(page.includes('sources.map('));
  assert.ok(page.includes('newsSources.slice('));
  assert.ok(page.includes('empresas con registros'));
  assert.ok(!page.includes('DERIVADO'));
  const sources = readFileSync('app/(root)/research/sources/page.tsx', 'utf8');
  assert.ok(!sources.includes('Tesis #'));
  assert.ok(sources.includes('map(auditFixLabel)'));
});

test('aviso de entradas de valoración en inglés se traduce', () => {
  assert.equal(auditFixLabel('Missing valuation inputs: shares_diluted, normalized_fcf_or_fcf_margin'), 'Faltan entradas de valoración: Acciones diluidas (media), FCF normalizado o margen FCF.');
});

test('documentos: tier en castellano y ausencia de fecha explícita', () => {
  const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
  assert.ok(page.includes('etiquetaTierFuente(document.source_tier)'));
  assert.ok(page.includes("'fecha desconocida'"));
});
