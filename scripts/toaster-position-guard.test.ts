import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// B3: los toasts abajo-derecha tapaban el FAB del Cerebro y el botón de enviar
// de su panel. Arriba-centro no tapan ninguno ni la navegación inferior móvil.
test('los toasts salen arriba-centro, lejos del FAB del Cerebro', () => {
  const toaster = readFileSync('components/ui/sonner.tsx', 'utf8');
  assert.ok(toaster.includes('position="top-center"'));
});
