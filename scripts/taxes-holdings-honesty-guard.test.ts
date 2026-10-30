/**
 * F240: /taxes «Posiciones fiscales» salía toda a «—» porque el backend
 * devolvía cost_basis_base/unrealized_pnl_base y la UI lista cost_basis,
 * market_value, unrealized_pnl y currency. Las claves deben coincidir y los
 * null pasan como None (NA), nunca como 0 inventado.
 * F94: al cambiar de ejercicio, el contenido del reporte debe resincronizarse
 * con el año pedido (antes el encabezado decía 2025 y el contenido era 2026).
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const backend = readFileSync('data-engine/app/services/tax_report_service.py', 'utf8');
const view = readFileSync('components/taxes/TaxesView.tsx', 'utf8');

test('el backend devuelve las claves que la UI lista', () => {
    for (const key of ['"cost_basis"', '"market_value"', '"unrealized_pnl"', '"currency"']) {
        assert.ok(backend.includes(key), `falta ${key} en build_tax_summary_rows`);
    }
    assert.match(view, /columns=\{\['ticker', 'quantity', 'cost_basis', 'market_value', 'unrealized_pnl'\]\}/);
});

test('los null de importes pasan como None, nunca como 0 inventado', () => {
    assert.ok(!/cost_basis_base or 0/.test(backend), 'cost_basis_base or 0 fabrica un 0 desde null');
    assert.ok(!/unrealized_pnl_base or 0/.test(backend), 'unrealized_pnl_base or 0 fabrica un 0 desde null');
});

test('F260: el informe mostrado se deriva del año pedido, sin estado espejo', () => {
    // La fuente de verdad es initialReport (llega con el año en el mismo
    // render); un useState(initialReport) dejaba un render con el informe
    // viejo bajo el título del año nuevo.
    assert.doesNotMatch(view, /useState<DataRecord \| null>\(initialReport\)/);
    assert.match(view, /reportForYear\(override, initialReport, year\)/);
    // el override de «Regenerar» se etiqueta con su ejercicio
    assert.match(view, /setOverride\(\{ year, report: fresh \}\)/);
    // RecordDetail sigue remontándose por ejercicio (su useState no resincroniza)
    assert.match(view, /key=\{recordDetailKey\(year, reportKey\)\}/);
});

test('F260: reportForYear solo acepta el override de su propio ejercicio', async () => {
    // @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
    const { reportForYear } = await import('../lib/taxes/report-state.ts');
    const servidor = { Ejercicio: 2025 };
    const regenerado = { Ejercicio: 2026, Generado: 'nuevo' };
    // sin override manda el informe del servidor para ese año
    assert.equal(reportForYear(null, servidor, 2025), servidor);
    // override del MISMO año (tras Regenerar) manda el regenerado
    assert.equal(reportForYear({ year: 2026, report: regenerado }, servidor, 2026), regenerado);
    // override de OTRO año no contamina: al cambiar de año manda el del servidor
    assert.equal(reportForYear({ year: 2026, report: regenerado }, servidor, 2025), servidor);
});

test('F94: la key cambia con el ejercicio aunque reportKey no cambie', async () => {
    // @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
    const { recordDetailKey } = await import('../components/taxes/record-detail-key.ts');
    assert.notEqual(recordDetailKey(2025, 0), recordDetailKey(2026, 0));
    assert.notEqual(recordDetailKey(2026, 0), recordDetailKey(2026, 1));
    assert.equal(recordDetailKey(2026, 0), '2026-0');
});
