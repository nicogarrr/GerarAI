import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('contribución mantiene fórmula y razones sin mostrar versión de implementación', () => {
  const page = readFileSync('app/(root)/portfolio/intelligence/page.tsx', 'utf8');
  assert.ok(!page.includes('{data.ledger_contribution.methodology}'));
  assert.ok(page.includes('Ganancias realizadas y no realizadas'));
  assert.ok(page.includes('Contribución = valor final − valor inicial − neto invertido + ingresos.'));
  assert.ok(page.includes('LEDGER_REASON_LABELS[row.reason'));
  assert.ok(page.includes('row.contribution_pnl === null'));
});

test('noticias conserva importación y análisis, plegados fuera de la lectura', () => {
  const page = readFileSync('app/(root)/research/news/page.tsx', 'utf8');
  const details = page.indexOf('<details');
  const close = page.indexOf('</details>', details);
  assert.ok(details > page.indexOf('<NewsEventsFlow'));
  assert.ok(page.indexOf('action={submitAnalyzeNews}') > details);
  assert.ok(page.indexOf('action={submitIngestFeed}') < close);
  assert.ok(!page.slice(details, page.indexOf('>', details)).includes('open'));
  assert.ok(readFileSync('components/portfolio/PortfolioSummary.tsx', 'utf8').includes('Coste de las posiciones'));
});
