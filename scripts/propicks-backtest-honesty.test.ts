import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const view =
  readFileSync('components/proPicks/WalkForwardResults.tsx', 'utf8') +
  readFileSync('lib/i18n/messages/es/propicks.json', 'utf8');

test('el backtest dice qué mide y qué no', () => {
  assert.ok(view.includes('momentum sobre 30 megacaps actuales'));
  assert.ok(view.includes('No mide la selección de calidad y valor de ProPicks'));
});

test('la metodología declara sesgo de supervivencia, muestra corta y snapshots', () => {
  assert.ok(view.includes('Sesgo de supervivencia'));
  assert.ok(view.includes('Muestra corta'));
  assert.ok(view.includes('snapshot point-in-time'));
});
