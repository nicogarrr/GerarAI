/**
 * Guard de la valoracion de la cuenta demo (lib/market/demo-valuation.ts):
 * solo Finnhub, divisa verificada, N/D honesto, sin precio de fill como
 * mercado, sin opciones valoradas con el subyacente, sin mezclar divisas.
 */
import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error -- node --test (--experimental-strip-types) exige la extension .ts
// en runtime; tsc la prohibe (TS5097). El supresor vive solo en este test.
import * as v from '../lib/market/demo-valuation.ts';
import type { DemoValuation, ValuationPosition, ValuationQuote, ValuedPosition } from '../lib/market/demo-valuation';

const valuePositions = v.valuePositions as (
    positions: ValuationPosition[],
    quotes: Record<string, ValuationQuote | null | undefined>,
    options?: { notQueried?: ReadonlySet<string> },
) => DemoValuation;

const asts: ValuationPosition = { instrumentKey: 'A:ASTS', name: 'AST SpaceMobile', kind: 'accion', currency: 'USD', quantity: 5, avgCost: 50 };
const live: ValuationQuote = { source: 'Finnhub', currency: 'USD', c: 60, t: Date.parse('2026-10-21T14:14:00Z') / 1000, kind: 'live' };
const yahoo: ValuationQuote = { source: 'Yahoo Finance', currency: 'EUR', c: 5, t: null, closeDate: '2026-10-20', kind: 'close' };

test('valora con Finnhub: valor, PyG no realizada y %', () => {
    const r = valuePositions([asts], { ASTS: live });
    assert.equal(r.rows[0].status, 'valorada');
    assert.equal(r.rows[0].marketValue, 300);
    assert.equal(r.rows[0].unrealizedPnl, 50);
    assert.equal(r.rows[0].unrealizedPct, 20);
    assert.equal(r.rows[0].currencyBasis, 'finnhub-listado');
    assert.deepEqual(r.coverage, { valued: 1, total: 1 });
    assert.deepEqual(r.totals, [{ currency: 'USD', marketValue: 300, unrealizedPnl: 50, costBasis: 250, valuedPositions: 1 }]);
});

test('sin cotizacion: N/D, nunca el precio de coste; fuera de totales', () => {
    for (const quotes of [{}, { ASTS: null }, { ASTS: { ...live, c: 0 } }, { ASTS: { ...live, c: Number.NaN } }]) {
        const r = valuePositions([asts], quotes);
        assert.equal(r.rows[0].status, 'sin-cotizacion');
        assert.equal(r.rows[0].marketValue, null);
        assert.equal(r.rows[0].price, null);
        assert.equal(r.rows[0].unrealizedPnl, null);
        assert.deepEqual(r.totals, []);
        assert.deepEqual(r.coverage, { valued: 0, total: 1 });
    }
});

test('Yahoo NO cuenta como valorada aunque traiga precio y divisa', () => {
    const san: ValuationPosition = { ...asts, instrumentKey: 'A:SAN.MC', name: 'Santander', currency: 'EUR', quantity: 10, avgCost: 4 };
    const r = valuePositions([san], { 'SAN.MC': yahoo });
    assert.equal(r.rows[0].status, 'fuente-no-aprobada');
    assert.equal(r.rows[0].marketValue, null);
    assert.equal(r.rows[0].price, null);
    assert.equal(r.rows[0].note, 'Sin cotización disponible de las fuentes admitidas.');
    assert.equal(r.rows[0].quoteLabel, null);
    assert.deepEqual(r.totals, []);
    assert.deepEqual(r.coverage, { valued: 0, total: 1 });
});

test('cobertura honesta: solo suma las valoradas', () => {
    const tsla: ValuationPosition = { ...asts, instrumentKey: 'A:TSLA', name: 'Tesla', quantity: 2, avgCost: 100 };
    const r = valuePositions([asts, tsla], { ASTS: live, TSLA: null });
    assert.deepEqual(r.coverage, { valued: 1, total: 2 });
    assert.equal(r.totals[0].marketValue, 300);
});

test('opciones no se valoran con el subyacente', () => {
    const option: ValuationPosition = { instrumentKey: 'O:ASTS:2026-12-18:call:50:100', name: 'ASTS Call', kind: 'opcion', currency: 'USD', quantity: 1, avgCost: 2 };
    const r = valuePositions([option], { ASTS: live });
    assert.equal(r.rows[0].status, 'opcion-no-valorada');
    assert.equal(r.rows[0].marketValue, null);
    assert.deepEqual(r.coverage, { valued: 0, total: 1 });
});

test('divisa: sin verificar => N/D; no coincide => N/D; GBp u otras => N/D; nunca por sufijo ni ausencia', () => {
    for (const currency of [null, undefined, '', 'GBp', 'CHF']) {
        const r = valuePositions([asts], { ASTS: { ...live, currency } });
        assert.equal(r.rows[0].status, 'divisa-no-coincide', String(currency));
        assert.equal(r.rows[0].marketValue, null);
    }
    const eurPos = valuePositions([{ ...asts, currency: 'EUR' }], { ASTS: live });
    assert.equal(eurPos.rows[0].status, 'divisa-no-coincide');
    assert.equal(eurPos.rows[0].marketValue, null);
});

test('misma accion en dos divisas: cada fila su valor, en cualquier orden', () => {
    const usd: ValuationPosition = { ...asts, quantity: 10, avgCost: 5 };
    const eur: ValuationPosition = { ...asts, currency: 'EUR', quantity: 7, avgCost: 4 };
    for (const order of [[usd, eur], [eur, usd]]) {
        const r = valuePositions(order, { ASTS: live });
        const byKey = new Map<string, ValuedPosition>(r.rows.map((row) => [v.valuationRowKey(row), row]));
        assert.equal(byKey.get('USD|A:ASTS')?.status, 'valorada');
        assert.equal(byKey.get('USD|A:ASTS')?.marketValue, 600);
        assert.equal(byKey.get('EUR|A:ASTS')?.status, 'divisa-no-coincide');
        assert.equal(byKey.get('EUR|A:ASTS')?.marketValue, null);
        assert.deepEqual(r.totals.map((t) => [t.currency, t.marketValue]), [['USD', 600]]);
        assert.equal(v.valuationMatches(r, order), true);
        assert.equal(v.valuationMatches(r, [order[0]]), false);
    }
});

test('valoracion caducada: cambia cantidad, coste o posiciones => no coincide', () => {
    const r = valuePositions([asts], { ASTS: live });
    assert.equal(v.valuationMatches(r, [asts]), true);
    assert.equal(v.valuationMatches(r, [{ ...asts, quantity: 6 }]), false);
    assert.equal(v.valuationMatches(r, [{ ...asts, avgCost: 51 }]), false);
    assert.equal(v.valuationMatches(r, [asts, { ...asts, instrumentKey: 'A:TSLA' }]), false);
    assert.equal(v.valuationMatches(r, []), false);
});

test('simbolos no consultados por el limite salen con motivo especifico', () => {
    const r = valuePositions([asts], {}, { notQueried: new Set(['ASTS']) });
    assert.equal(r.rows[0].status, 'no-consultada');
    assert.match(r.rows[0].note ?? '', /límite de 25 símbolos/);
});

test('totales por divisa separados', () => {
    const msft: ValuationPosition = { ...asts, instrumentKey: 'A:ASML', name: 'ASML', currency: 'EUR', quantity: 1, avgCost: 1 };
    const r = valuePositions([asts, msft], { ASTS: live, ASML: { ...live, currency: 'EUR', c: 3 } });
    assert.deepEqual(r.totals.map((t) => t.currency), ['EUR', 'USD']);
    assert.equal(r.totals[0].marketValue, 3);
    assert.equal(r.totals[1].marketValue, 300);
});

test('etiquetas: en vivo con hora, cierre con fecha, sin fecha no inventa', () => {
    assert.match(v.quoteLabel(live), /^16:14 \(hora de Madrid\) · en vivo$/);
    assert.match(v.quoteLabel(yahoo), /^cierre del 20 oct$/);
    assert.equal(v.quoteLabel({ source: 'Yahoo Finance', c: 5, t: null, closeDate: null, kind: 'close' }), 'cierre de fecha desconocida');
    assert.match(v.quoteLabel({ source: 'Finnhub', c: 5, t: Date.parse('2026-10-20T20:00:00Z') / 1000, kind: 'close' }), /^último cierre, dato de 20 oct 22:00$/);
});

test('simbolo de la clave y parseo del listado de Finnhub', () => {
    assert.equal(v.symbolFromKey('A:ASTS'), 'ASTS');
    assert.equal(v.symbolFromKey('O:ASTS:2026-12-18:call:50:100'), null);
    const map: Map<string, string> = v.parseListingCurrencies([
        { symbol: 'asts', currency: 'USD' },
        { symbol: 'X', currency: '' },
        { currency: 'USD' },
        null,
    ]);
    assert.deepEqual([...map], [['ASTS', 'USD']]);
    assert.equal(v.parseListingCurrencies({ error: 'x' }).size, 0);
});
