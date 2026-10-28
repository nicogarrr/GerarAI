import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('mobile access is in its reserved navigation row, not over page controls', () => {
  const brain = readFileSync('components/brain/GlobalBrain.tsx', 'utf8') + '\n' + readFileSync('components/brain/GlobalBrainPanel.tsx', 'utf8');
  const nav = readFileSync('components/layout/BottomNav.tsx', 'utf8');
  // #1848: la burbuja es ahora un envoltorio (boton + pista "Pregunta al
  // Cerebro"), asi que el literal cambia de orden pero NO de significado:
  // sigue oculta en movil (hidden), fija y visible desde md (fixed + md:flex).
  assert.ok(brain.includes('group fixed'));
  assert.ok(brain.includes('hidden items-center gap-2 md:flex'));
  assert.ok(!brain.includes('fabHidden'));
  assert.ok(!brain.includes('translate-y-24'));
  // #1805: el Cerebro es una celda más de la rejilla (6 columnas), ya no una
  // franja apilada encima de la barra; sigue en la fila de navegación.
  assert.ok(nav.includes('grid-cols-6'));
  assert.ok(nav.indexOf('<ul') < nav.indexOf('>Cerebro'));
  assert.ok(nav.includes("new Event('gerarai:open-brain')"));
});
