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

// La parte de inventario (/research/data-health) se eliminó entera por
// decisión de Nico (2026-10-20); se conserva lo que fija sobre /research/sources.
test('sources no inventa identificadores y traduce los motivos de bloqueo', () => {
  const sources = readFileSync('app/(root)/research/sources/page.tsx', 'utf8');
  assert.ok(!sources.includes('Tesis #'));
  assert.ok(sources.includes('map((fix) => auditFixLabel(fix, locale))'));
});

test('aviso de entradas de valoración en inglés se traduce', () => {
  assert.equal(auditFixLabel('Missing valuation inputs: shares_diluted, normalized_fcf_or_fcf_margin'), 'Faltan entradas de valoración: Acciones diluidas (media), FCF normalizado o margen FCF.');
});

test('documentos: tier en castellano y ausencia de fecha explícita', () => {
  const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
  assert.ok(page.includes('etiquetaTierFuente(document.source_tier, locale)'));
  assert.ok(page.includes("t('research.fichaUnknownDate')"));
  assert.equal(JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).fichaUnknownDate, 'fecha desconocida');
});

test('auditFixLabel: lista de entradas faltantes sin claves crudas ni comodines', () => {
  assert.equal(
    auditFixLabel('Faltan entradas de valoración (variables del modelo): asset_value, aum, segment_*_operating_metric, segment_*_valuation_multiple'),
    'Faltan entradas de valoración (variables del modelo): valor de los activos, activos bajo gestión (AUM), métrica operativa por segmento, múltiplo de valoración por segmento',
  );
});
