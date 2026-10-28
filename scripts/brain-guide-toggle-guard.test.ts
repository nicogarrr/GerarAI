import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// El selector de ticker de la guía no puede volver a ser un input suelto en
// la cabecera del Cerebro: parece una herramienta de desarrollo. Se abre
// desde un botón "Guía" y se mantiene visible mientras haya ticker activo.
test('el ticker de la guía se pliega tras un botón y conserva su aria-label', () => {
  const brain = readFileSync('components/brain/GlobalBrain.tsx', 'utf8') + '\n' + readFileSync('components/brain/GlobalBrainPanel.tsx', 'utf8');
  assert.ok(brain.includes('showGuideInput || guideTicker'));
  assert.ok(brain.includes('aria-label="Abrir la guía de investigación por empresa"'));
  assert.ok(brain.includes('ariaLabel="Ticker de la guía de investigación"'));
  assert.ok(brain.includes('setShowGuideInput(false)'));
  assert.match(brain, />\s*Guía\s*<\/button>/);
});
