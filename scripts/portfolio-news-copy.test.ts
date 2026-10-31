import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('contribución mantiene fórmula y razones sin mostrar versión de implementación', () => {
  const page = readFileSync('app/(root)/portfolio/intelligence/page.tsx', 'utf8');
  const dict = JSON.parse(readFileSync('lib/i18n/messages/es/portfolio.json', 'utf8'));
  assert.ok(!page.includes('{data.ledger_contribution.methodology}'));
  assert.ok(page.includes('portfolio.intelligence.contributionNoteStart'), 'la nota sale del diccionario i18n');
  assert.ok(dict.intelligence.contributionNoteStart.includes('Ganancias realizadas y no realizadas'), 'valor es de la nota');
  assert.ok(dict.intelligence.contributionNoteEnd.includes('Contribución = valor final − valor inicial − neto invertido + ingresos.'), 'fórmula intacta en el diccionario');
  assert.ok(page.includes('ledgerReasonLabel(ti, row.reason'), 'razones del ledger vía i18n');
  assert.ok(dict.intelligence.ledger_missing_ledger.length > 0, 'razones del ledger en el diccionario');
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
  const summarySrc = readFileSync('components/portfolio/PortfolioSummary.tsx', 'utf8');
  assert.ok(summarySrc.includes('portfolio.summary.costTitle'), 'título de coste vía i18n');
  const summaryDict = JSON.parse(readFileSync('lib/i18n/messages/es/portfolio.json', 'utf8'));
  assert.equal(summaryDict.summary.costTitle, 'Coste de las posiciones', 'valor es del título de coste');
});
