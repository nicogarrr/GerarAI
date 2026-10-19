import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('mobile access is in its reserved navigation row, not over page controls', () => {
  const brain = readFileSync('components/brain/GlobalBrain.tsx', 'utf8');
  const nav = readFileSync('components/layout/BottomNav.tsx', 'utf8');
  assert.ok(brain.includes('className="hidden md:flex fixed'));
  assert.ok(!brain.includes('fabHidden'));
  assert.ok(!brain.includes('translate-y-24'));
  // #1805: el Cerebro es una celda más de la rejilla (6 columnas), ya no una
  // franja apilada encima de la barra; sigue en la fila de navegación.
  assert.ok(nav.includes('grid-cols-6'));
  assert.ok(nav.indexOf('<ul') < nav.indexOf('>Cerebro'));
  assert.ok(nav.includes("new Event('gerarai:open-brain')"));
});
