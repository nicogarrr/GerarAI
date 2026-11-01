import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

// Radix da tabIndex=0 al TabsContent: el panel de pestañas entra en el orden
// de tabulación. Un outline-none en sus clases base tapa el anillo global
// :focus-visible (utilities > base) y el panel enfocado queda SIN indicador
// visible (WCAG 2.2 SC 2.4.7). Medido en render: outline-style "none".
test('a11y: TabsContent no tapa el indicador de foco global', () => {
  const src = readFileSync('components/ui/tabs.tsx', 'utf8');
  const slot = src.indexOf('data-slot="tabs-content"');
  assert.ok(slot !== -1, 'no se encontró el TabsContent (data-slot=tabs-content) en ui/tabs.tsx');
  const block = src.slice(slot, slot + 600);
  assert.ok(
    !/outline-none/.test(block),
    'TabsContent con outline-none: el panel de pestañas enfocado no muestra indicador',
  );
});
