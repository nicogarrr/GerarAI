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
  const simple = source.match(/<span>\{loading \? 'Actualizando selección\.\.\.' : 'Actualizar selección'\}<\/span>/g) ?? [];
  assert.equal(simple.length, 1, 'el botón principal «Actualizar selección» cambia su etiqueta mientras carga');
  const condicional = source.match(/<span>\{lastGenerated \? \(loading \? 'Actualizando selección\.\.\.' : 'Actualizar selección'\) : \(loading \? 'Generando selección\.\.\.' : 'Generar selección ahora'\)\}<\/span>/g) ?? [];
  assert.equal(condicional.length, 1, 'el botón del estado vacío anuncia «Actualizando selección...» al actualizar y «Generando selección...» al generar el primer run');
  const teal = source.match(/bg-teal-600 text-white/g) ?? [];
  assert.equal(teal.length, 2, 'texto blanco legible también deshabilitado (opacity-50)');
});
