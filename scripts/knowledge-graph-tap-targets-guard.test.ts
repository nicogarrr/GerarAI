import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

// Guard móvil (390px): todos los controles interactivos del grafo deben tener
// objetivo táctil >= 44px (convención del repo: h-11/min-h-11 en móvil,
// min-h-9 en desktop). Antes los botones sm (36px) y las filas de nodos
// (texto desnudo ~20px) quedaban por debajo en pantallas táctiles.
const src = readFileSync('components/knowledge-graph/KnowledgeGraphCanvas.tsx', 'utf8');
const TAG = /<Button\b(?:\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}|[^>{])*>/g;

test('todos los botones del grafo tienen objetivo táctil de 44px en móvil', () => {
  const tags = src.match(TAG) ?? [];
  const sm = tags.filter(t => t.includes('size="sm"'));
  assert.ok(sm.length >= 8, `se esperaban >=8 botones sm, hay ${sm.length}`);
  for (const tag of sm) {
    assert.ok(tag.includes('min-h-11'), `botón sm sin min-h-11: ${tag.slice(0, 100)}`);
    assert.ok(tag.includes('md:min-h-9'), `botón sm sin md:min-h-9: ${tag.slice(0, 100)}`);
  }
  const plain = src.match(/<button[\s\S]*?type="button"[\s\S]*?>/g) ?? [];
  assert.ok(plain.length >= 2, 'hay botones planos de fila/vecinos');
  for (const tag of plain) {
    assert.ok(tag.includes('min-h-11'), `botón plano sin min-h-11: ${tag.slice(0, 100)}`);
  }
});
