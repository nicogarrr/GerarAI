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
  const condicional = source.match(/<span>\{emptyStateNeedsRun \? \(loading \? 'Generando selección\.\.\.' : 'Generar selección ahora'\) : \(loading \? 'Actualizando selección\.\.\.' : 'Actualizar selección'\)\}<\/span>/g) ?? [];
  assert.equal(condicional.length, 1, 'el botón del estado vacío anuncia «Actualizando selección...» al actualizar y «Generando selección...» al generar (primer run o run con 0 aptas): la etiqueta dice la acción real');
  assert.doesNotMatch(source, /bg-teal-600/, 'el primario vive en Button, no en overrides locales');
});
