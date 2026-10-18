import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
test('refresh announces consultation result without claiming a new run', () => {
  const source = readFileSync('components/proPicks/EnhancedProPicksContent.tsx', 'utf8');
  assert.match(source, /Selección consultada:/);
  assert.match(source, /0 empresas con estos filtros/);
  assert.match(source, /loading \? 'Consultando selección\.\.\.' : refreshStatus/);
  assert.match(source, /Los resultados anteriores se conservan/);
});

test('el botón anuncia el estado por sí mismo (QA: sin feedback)', () => {
  const source = readFileSync('components/proPicks/EnhancedProPicksContent.tsx', 'utf8');
  const buttons = source.match(/<span>\{loading \? 'Actualizando selección\.\.\.' : 'Actualizar selección'\}<\/span>/g) ?? [];
  assert.equal(buttons.length, 2, 'los dos botones «Actualizar selección» cambian su etiqueta mientras cargan');
  const teal = source.match(/bg-teal-600 text-white/g) ?? [];
  assert.equal(teal.length, 2, 'texto blanco legible también deshabilitado (opacity-50)');
});
