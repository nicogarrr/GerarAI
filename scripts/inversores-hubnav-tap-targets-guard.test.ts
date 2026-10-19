import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

// Guard móvil (390px): los chips del HubNav de /inversores medían 36px de
// alto (py-2 + text-sm), por debajo del objetivo táctil de 44px. Deben llevar
// min-h-11 en móvil y md:min-h-0 para conservar la altura compacta en desktop.
const src = readFileSync('app/(root)/inversores/_components/HubNav.tsx', 'utf8');

test('los chips del HubNav de /inversores tienen objetivo táctil de 44px en móvil', () => {
  const linkClass = src.match(/className=\{`([\s\S]*?)`\}/);
  assert.ok(linkClass, 'se encuentra la clase del Link');
  const cls = linkClass[1];
  assert.ok(cls.includes('min-h-11'), 'falta min-h-11 (44px móvil)');
  assert.ok(cls.includes('md:min-h-0'), 'falta md:min-h-0 (desktop compacto)');
  assert.ok(cls.includes('inline-flex') && cls.includes('items-center'), 'el chip centra el texto con inline-flex items-center');
});
