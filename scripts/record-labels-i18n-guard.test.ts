/**
 * Guard de etiquetas de `RecordList` / `RecordDetail` (F312).
 *
 * Las columnas y campos de estos dos componentes se elegían por clave del
 * backend y se pintaban tal cual: en /corporate-actions se leía
 * `ticker · action_type · description · effective_date · ratio · status` y en
 * /plan `date · amount · currency · note · external_id` sobre el RecordDetail
 * `PLAN_EXISTS · MONTHLY_CONTRIBUTION · TARGET_ALLOCATIONS`. Dos de esas
 * columnas moreover NO EXISTEN en la respuesta del backend, así que solo
 * producían «—»:
 *   - corporate_actions._payload -> id, ticker, action_type, effective_date,
 *     ratio, description, applied, applied_at (NO hay `status`);
 *   - plan.list_contributions -> id, date, amount, currency, note
 *     (`external_id` solo existe en el POST de alta, no en el listado).
 * Y `isApplied()` miraba `record.status === 'applied'`, una condición que no
 * puede darse: el botón «Aplicar» quedaba habilitado sobre acciones ya
 * aplicadas.
 *
 * Lo que comprueba:
 *  1. `RecordDetail` tiene el mismo mecanismo de etiquetas que `RecordList`,
 *     con el mismo fallback a la clave cruda (las claves sin etiqueta NUNCA se
 *     ocultan, pero tampoco se muestran en crudo cuando hay mapa).
 *  2. Ninguna columna listada puede quedarse sin etiqueta visible.
 *  3. Las claves que el backend devuelve de verdad están todas etiquetadas, y
 *     las columnas muertas (`status`, `external_id`) ya no se listan.
 *  4. Los arrays/objetos anidados no se serializan a JSON crudo en la celda.
 *  5. `rowActions` puede sustituir la fila mutada con la respuesta del backend.
 *
 * Ejecución: node --experimental-strip-types --test scripts/record-labels-i18n-guard.test.ts
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import test from 'node:test';

const here = dirname(fileURLToPath(import.meta.url));
const source = (rel: string) => readFileSync(join(here, '..', rel), 'utf8');

const recordViews = source('components/data/RecordViews.tsx');
const corporateActions = source('components/corporate-actions/CorporateActionsView.tsx');
const plan = source('components/plan/PlanView.tsx');
const corporateActionsRoute = source('data-engine/app/api/routes/corporate_actions.py');
const planService = source('data-engine/app/services/investment_plan_service.py');
const planRoute = source('data-engine/app/api/routes/plan.py');

/** Claves declaradas en un `const X: Record<string, string> = { ... };`. */
function labelMapKeys(view: string): Set<string> {
  // Los mapas de etiquetas viven dentro del componente (carril C: necesitan
  // la t() del hook) o en funciones que la reciben: cierre indentado y
  // forma `function f(...): Record<string, string> { return {...}; }`.
  const blocks = [
    ...[...view.matchAll(/Record<string, string>\s*=\s*\{([\s\S]*?)\n\s*\};/g)].map((match) => match[1]),
    ...[...view.matchAll(/Record<string, string> \{\s*return \{([\s\S]*?)\n\s*\};/g)].map((match) => match[1]),
    ...[...view.matchAll(/columnLabels=\{\{([\s\S]*?)\}\}/g)].map((match) => match[1]),
  ];
  const keys = new Set<string>();
  for (const block of blocks) {
    for (const [, key] of block.matchAll(/^\s*(\w+):/gm)) keys.add(key);
  }
  return keys;
}

/** Cada array literal de `columns={[...]}` de la vista. */
function listedColumns(view: string): string[][] {
  return [...view.matchAll(/columns=\{\[([\s\S]*?)\]\}/g)].map((match) =>
    [...match[1].matchAll(/'([^']+)'/g)].map((entry) => entry[1]),
  );
}

/** Claves del dict que devuelve una función del data-engine (su último return). */
function returnedKeys(file: string, from: string, to: string): string[] {
  const begin = file.indexOf(from);
  // `to` se busca DESPUES de `from`: helpers/@staticmethod pueden estar antes.
  const end = file.indexOf(to, begin + from.length);
  const block = begin >= 0 && end > begin ? file.slice(begin, end) : '';
  assert.ok(block.length > 0, `no se encontró ${from} en la fuente del backend`);
  // El ÚLTIMO return es el que responde la consulta; los anteriores son
  // salidas tempranas (p. ej. `{"plan_exists": False}`).
  const start = Math.max(block.lastIndexOf('return {'), block.lastIndexOf('return ['));
  assert.ok(start >= 0, `${from} no devuelve un dict literal`);
  const returned = block.slice(start);
  return [...returned.matchAll(/"([a-z_]+)":/g)].map((match) => match[1]);
}

void test('RecordDetail etiqueta los campos con el mismo mecanismo que RecordList', () => {
  // Mismo nombre de prop y mismo fallback: sin mapa, la clave cruda sigue
  // visible (nunca se oculta), pero con mapa el usuario no lee `PLAN_EXISTS`.
  assert.match(recordViews, /columnLabels\?: Record<string, string>;/);
  assert.match(recordViews, /\{columnLabels\?\.\[key\] \?\? key\}/);
  assert.equal(
    recordViews.match(/columnLabels\?\.\[key\] \?\? key/g)?.length,
    1,
    'el fallback de RecordDetail aparece una sola vez (el de RecordList lo cubre su propio guard)',
  );
  // El patrón de RecordList no se toca: lo fija taxes-holdings-headers-guard.
  assert.equal(recordViews.match(/columnLabels\?\.\[column\] \?\? column/g)?.length, 2);
});

void test('toda columna listada tiene etiqueta visible', () => {
  for (const [name, view] of [['CorporateActionsView', corporateActions], ['PlanView', plan]] as const) {
    const labels = labelMapKeys(view);
    const columnLists = listedColumns(view);
    assert.ok(columnLists.length > 0, `${name} no declara columnas explícitas`);
    for (const columns of columnLists) {
      for (const column of columns) {
        assert.ok(labels.has(column), `${name}: la columna «${column}» se pinta con la clave cruda del backend`);
      }
    }
  }
});

void test('las columnas muertas del backend no se listan', () => {
  // `status` no existe en corporate_actions._payload y `external_id` no en
  // plan.list_contributions: listarlas solo producía «—».
  assert.ok(!corporateActionsRoute.slice(0, corporateActionsRoute.indexOf('@router.post("/splits/sync")')).includes('"status"'));
  assert.ok(!corporateActions.includes("'status'"));
  assert.ok(!plan.includes("'external_id'"));
  assert.ok(!planRoute.slice(planRoute.indexOf('def list_contributions'), planRoute.indexOf('@router.post("/contributions"')).includes('"external_id"'));
});

void test('el estado de una acción corporativa viene de applied / applied_at', () => {
  // `record.status === 'applied'` no puede ser cierto: el backend nunca manda
  // `status`, así que el botón «Aplicar» quedaba habilitado tras aplicar.
  assert.ok(!corporateActions.includes('record.status'));
  assert.match(corporateActions, /record\.applied === true/);
  assert.match(corporateActions, /record\.applied_at/);
  // Y las columnas existen de verdad en la respuesta.
  for (const key of ['"applied"', '"applied_at"']) {
    assert.ok(corporateActionsRoute.includes(key), `falta ${key} en corporate_actions._payload`);
  }
});

void test('el plan etiqueta todas las claves que devuelve el backend', () => {
  const labels = labelMapKeys(plan);
  const metrics = returnedKeys(planService, 'def plan_metrics', 'def _expected_base');
  const drift = returnedKeys(planService, 'def drift_analysis', '@staticmethod');
  const contributions = returnedKeys(planRoute, 'def list_contributions', '@router.post("/contributions"');
  for (const key of [...metrics, ...drift, ...contributions]) {
    assert.ok(labels.has(key), `PlanView no etiqueta la clave «${key}» que devuelve el backend`);
  }
  // El `id` lo añade la ruta, no plan_metrics (metrics["id"] = plan.id).
  assert.match(planRoute, /metrics\["id"\] = plan\.id/);
  assert.ok(labels.has('id'), 'PlanView no etiqueta la clave «id» que añade la ruta de /api/plan');
  // Los tres RecordList/RecordDetail de la vista van etiquetados.
  assert.equal((plan.match(/columnLabels=\{[A-Z_]+\}/g) ?? []).length, 3);
});

void test('los valores anidados no se serializan como JSON crudo en la celda', () => {
  // `JSON.stringify` dentro de un line-clamp escondía el dato detrás de un
  // bloque de código truncado con las claves internas en crudo.
  assert.ok(!recordViews.includes('JSON.stringify(value)'));
  assert.match(recordViews, /function describeValue\(value: unknown, depth: number\): string \{/);
  // Y lo que no cabe se cuenta, no desaparece sin aviso.
  assert.match(recordViews, /\+\$\{rest\} más/);
});

void test('una fila mutada se actualiza con la respuesta del backend', () => {
  // Sin esto, «Aplicar» mostraba un toast y la fila seguía con el botón
  // habilitado hasta un refresco manual.
  assert.match(recordViews, /rowActions\?: \(record: DataRecord, index: number, replace: ReplaceRecord\) => ReactNode;/);
  assert.match(recordViews, /\{rowActions\(record, index, replaceRecord\(index\)\)\}/);
  assert.match(corporateActions, /const appliedRecord = await applyCorporateAction\(actionId\);/);
  assert.match(corporateActions, /replace\(appliedRecord\);/);
  // El estado aplicado no se inventa en local: sale del payload del backend.
  assert.match(corporateActions, /isApplied\(record\)/);
});
