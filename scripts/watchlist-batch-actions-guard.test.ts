/**
 * Guard: las filas de listas no pueden volver a llamar server actions por
 * símbolo una a una. Medido en prod (31-oct-2026, cuenta Claude B, 390px):
 * 24 POSTs de acción por carga de /watchlist (2 funciones × 12 filas),
 * ~7.6s de tiempo de función agregado — el patrón que agota la CPU activa
 * del plan Hobby de Vercel. Las filas deben pasar por batchedSymbol.
 */
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

test('ExtendedHoursLine pide cotizaciones extendidas vía batch, no por fila', () => {
    const src = readFileSync('components/common/ExtendedHoursLine.tsx', 'utf8');
    assert.ok(src.includes("batchedSymbol('extended-quote'"), 'ExtendedHoursLine debe usar batchedSymbol');
    assert.ok(src.includes('getExtendedQuotes('), 'ExtendedHoursLine debe usar la acción batch getExtendedQuotes');
    assert.ok(!src.includes('getExtendedQuote('), 'ExtendedHoursLine no debe llamar getExtendedQuote (por fila)');
});

test('AnalystTargetLine pide objetivos vía batch, no por fila', () => {
    const src = readFileSync('components/common/AnalystTargetLine.tsx', 'utf8');
    assert.ok(src.includes("batchedSymbol(\n                'analyst-targets'") || src.includes("batchedSymbol('analyst-targets'"), 'AnalystTargetLine debe usar batchedSymbol');
    assert.ok(src.includes('getListingAnalystTargetsBatch('), 'AnalystTargetLine debe usar la acción batch');
    assert.ok(!src.includes('getListingAnalystTargets(symbol'), 'AnalystTargetLine no debe llamar getListingAnalystTargets por fila');
});

test('las acciones batch existen con autenticación y techo defensivo', () => {
    const watchlist = readFileSync('lib/actions/watchlist.actions.ts', 'utf8');
    assert.ok(watchlist.includes('export async function getExtendedQuotes('), 'falta getExtendedQuotes');
    const analyst = readFileSync('lib/actions/analyst-targets.actions.ts', 'utf8');
    assert.ok(analyst.includes('export async function getListingAnalystTargetsBatch('), 'falta getListingAnalystTargetsBatch');
    assert.ok(analyst.includes('requireAuthenticatedUser'), 'el batch de objetivos debe exigir sesión');
});
