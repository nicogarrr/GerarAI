import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
// @ts-expect-error Node strip-types requires the explicit TS extension.
import { factDisplayAudit } from '../lib/research/fact-display-audit.ts';
const bad = { metric: 'eps_diluted', unit: 'USD/share', period: '2020-03-31:Q1', value: '17600000.000000' };
test('audited ASTS Q1 2020 anomaly is quarantined without guessing corrected EPS', () => {
  assert.match(factDisplayAudit('ASTS', bad)!, /linaje/);
  assert.equal(factDisplayAudit('ASTS', {...bad, value: '-0.39'}), null);
  assert.equal(factDisplayAudit('ASTS', {...bad, value: '0'}), null);
  assert.equal(factDisplayAudit('OTHER', bad), null);
  assert.equal(factDisplayAudit('ASTS', {...bad, metric: 'net_income'}), null);
});
test('EPS dimensional mismatch is not displayed as a valid figure', () => {
  assert.match(factDisplayAudit('ASTS', {...bad, unit: 'USD'})!, /unidad/);
  assert.match(factDisplayAudit('ASTS', {...bad, unit: 'shares'})!, /unidad/);
  assert.equal(factDisplayAudit('ASTS', {...bad, unit: 'EUR/share', value: '2.8'}), null);
});
test('mobile and desktop facts both call the audit with ticker and use N/D', () => {
  // La tabla/tarjetas de hechos viven en FactsPanels; la ficha las compone.
  const panels = readFileSync('components/research/FactsPanels.tsx', 'utf8');
  const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
  assert.match(panels, /const audit = factDisplayAudit\(ticker, fact\)/);
  assert.match(panels, /audit \? 'N\/D' : <><FactValueLink/);
  assert.match(panels, /factDisplayAudit\(ticker, fact\) \? <span/);
  assert.match(page, /<FactTable ticker=\{ticker\}/);
});
