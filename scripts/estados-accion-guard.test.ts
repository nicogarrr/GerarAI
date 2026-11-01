import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
const ES_INVESTORS_JSON = readFileSync('lib/i18n/messages/es/investors.json', 'utf8');
// Los textos de Pro Picks viven en el diccionario es (i18n): se comprueban junto al código.
const ES_PROPICKS_JSON = readFileSync('lib/i18n/messages/es/propicks.json', 'utf8');

const read = (p: string) => readFileSync(p, 'utf8');

test('inversores: cuenta nueva sin 13F ofrece la acción real de sincronizar', () => {
  // Carteras se fusiona en /inversores (decisión de Nico, 2026-10-20): el estado vacío vive en el hub.
  const page = (read('app/(root)/inversores/page.tsx') + ES_INVESTORS_JSON);
  assert.ok(page.includes('SyncPortfoliosButton'), 'la página de carteras debe usar SyncPortfoliosButton');
  assert.ok(page.includes('Aún no hay carteras descargadas en esta cuenta.'));
  assert.ok(page.includes('.every((investor) => !investor.report_date)'), 'el estado vacío solo aparece cuando NINGÚN inversor tiene 13F descargado');

  const button = (read('app/(root)/inversores/_components/SyncPortfoliosButton.tsx') + ES_INVESTORS_JSON);
  assert.ok(button.includes('Sincronizar carteras ahora'));
  assert.ok(!button.includes('bg-teal-600'), 'sin override de primario: usa el Button por defecto');
  assert.ok(button.includes('Sincronización en curso'), 'confirma que la sincronización quedó encolada');
});

test('más compradas: sin dos trimestres de 13F ofrece la misma acción de sincronizar', () => {
  // Movidas a vistas de /ownership (Movimientos 13F) por decision de Nico, WhatsApp 2026-10-20 00:59.
  // El texto vive en es/ownership.json: solo se añade la sección de Más compradas.
  const page = read('app/(root)/ownership/_components/MostBought.tsx') + JSON.stringify(JSON.parse(read('lib/i18n/messages/es/ownership.json')).mostBought);
  assert.ok(page.includes('SyncPortfoliosButton'), 'más-compradas reutiliza el botón de sincronización en su estado vacío');
  assert.ok(page.includes('faltan dos trimestres de 13F sincronizados.'), 'la razón honesta se conserva');
});


test('ficha de inversor: con 13F sin sincronizar ofrece la acción en vez de «N/D · 0 posiciones»', () => {
  const page = read('app/(root)/inversores/[slug]/page.tsx');
  assert.ok(page.includes('SyncPortfoliosButton'), 'la ficha reutiliza el botón de sincronización');
  assert.ok(page.includes('investor.has_13f && portfolio.positions.length === 0'), 'solo cuando el inversor tiene 13F y no hay posiciones');
});

test('la acción de sincronización llama a la ruta async que encola el actor', () => {
  assert.ok(read('lib/actions/investors.actions.ts').includes('/api/ownership/managers/sync-async'));
  const route = read('data-engine/app/api/routes/ownership.py');
  assert.ok(route.includes('"/managers/sync-async"'));
  assert.ok(route.includes('sync_investor_holdings.send('), 'la ruta encola el actor existente, no reimplementa el trabajo');
});

test('propicks: sin run publicado el botón genera la selección, no relee el vacío', () => {
  const src = (read('components/proPicks/EnhancedProPicksContent.tsx') + ES_PROPICKS_JSON);
  assert.ok(src.includes('handleGenerateRun'), 'debe existir la acción de generar el primer run');
  assert.ok(src.includes('generateFunnelRunNow'));
  assert.ok(src.includes('Generar selección ahora'));
  assert.ok(src.includes('Actualizando selección...'), 'el botón anuncia la actualización en curso también en el estado vacío');
  assert.ok(src.includes("const emptyStateNeedsRun = !lastGenerated || passedCount === 0;"), 'una sola condición: sin run (o con 0 aptas) hay que generar de nuevo');
  assert.ok(src.includes("onClick={emptyStateNeedsRun ? handleGenerateRun : handleRefresh}"), 'con run publicado y aptas actualiza; sin run (o con 0 aptas) genera de nuevo');
  assert.ok(read('lib/actions/propicks-funnel.actions.ts').includes("'/api/propicks/runs', { method: 'POST' }"));
});
