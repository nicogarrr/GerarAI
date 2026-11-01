import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// Los textos de Pro Picks viven en el diccionario es (i18n): se comprueban junto al código.
const ES_PROPICKS_JSON = readFileSync('lib/i18n/messages/es/propicks.json', 'utf8');
test('refresh announces consultation result without claiming a new run', () => {
  const source = (readFileSync('components/proPicks/EnhancedProPicksContent.tsx', 'utf8') + ES_PROPICKS_JSON);
  assert.match(source, /Selección consultada:/);
  assert.match(source, /0 empresas con estos filtros/);
  assert.match(source, /loading \? t\('propicks\.content\.querying'\) : refreshStatus/);
  assert.match(source, /Los resultados anteriores se conservan/);
});

test('el botón anuncia el estado por sí mismo (QA: sin feedback)', () => {
  const source = (readFileSync('components/proPicks/EnhancedProPicksContent.tsx', 'utf8') + ES_PROPICKS_JSON);
  const simple = source.match(/<span>\{loading \? t\('propicks\.content\.refreshing'\) : t\('propicks\.content\.refresh'\)\}<\/span>/g) ?? [];
  assert.equal(simple.length, 1, 'el botón principal «Actualizar selección» cambia su etiqueta mientras carga');
  const condicional = source.match(/<span>\{emptyStateNeedsRun \? \(loading \? t\('propicks\.content\.generating'\) : t\('propicks\.content\.generateNow'\)\) : \(loading \? t\('propicks\.content\.refreshing'\) : t\('propicks\.content\.refresh'\)\)\}<\/span>/g) ?? [];
  assert.equal(condicional.length, 1, 'el botón del estado vacío anuncia «Actualizando selección...» al actualizar y «Generando selección...» al generar (primer run o run con 0 aptas): la etiqueta dice la acción real');
  assert.doesNotMatch(source, /bg-teal-600/, 'el primario vive en Button, no en overrides locales');
});
