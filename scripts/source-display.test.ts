import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { auditFixDisplay, sourceDisplay } from '../lib/research/source-display.ts';

test('fuentes conocidas se traducen sin convertir una fuente futura en otra', () => {
  assert.equal(sourceDisplay('primary_official'), 'Fuente oficial primaria');
  assert.equal(sourceDisplay('yahoo_finance_intraday'), 'Yahoo Finance · intradía');
  assert.equal(sourceDisplay('future_provider'), 'future provider');
});

test('bloqueos conocidos y métricas se presentan en español sin cambiar cifras', () => {
  assert.equal(auditFixDisplay('No calculation trace -> no valuation.'), 'Falta el desglose del cálculo de valoración.');
  assert.equal(auditFixDisplay('Faltan normalized_fcf_or_fcf_margin, shares_diluted (2025).'), 'Faltan FCF normalizado o margen FCF, Acciones diluidas (media) (2025).');
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
  assert.ok(sources.includes('map(auditFixDisplay)'));
});
