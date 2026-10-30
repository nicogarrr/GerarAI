import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const src = readFileSync('components/research/CompanyHeaderQuote.tsx', 'utf8');

test('closed-market variation is shown only from official-close fields', () => {
  const block = src.slice(src.indexOf('data-testid="close-change"') - 400, src.indexOf('data-testid="close-change"') + 1600);
  assert.match(block, /quote\.session === 'cerrado'/);
  assert.match(block, /close_change_date && quote\.close_change_previous_date/);
  assert.doesNotMatch(block, /previous_close\b/);
});

test('cabecera limpia: sin «Más detalle» ni líneas de procedencia/comparativa (Nico, 30-oct-2026)', () => {
  // Nico (WhatsApp, 30-oct-2026): «Quita lo de más detalle y quita lo de Yahoo
  // y textos de ese estilo». La cabecera deja solo precio y variación; la
  // sesión y la hora siguen en el rótulo superior (extendedQuoteLabel) y la
  // fecha del cierre anterior en la tira de métricas.
  assert.doesNotMatch(src, /Más detalle/);
  assert.doesNotMatch(src, /quote-detail/);
  assert.doesNotMatch(src, /Último cierre vs anterior/);
  assert.doesNotMatch(src, /quote!\.source/);
});
