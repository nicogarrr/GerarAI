// @vitest-environment node
import { describe, expect, it } from 'vitest';

import {
    parseListingCurrencies, quoteLabel, resolveQuoteCurrency, symbolFromKey, valuationMatches, valuationRowKey,
    valuePositions, type ValuationPosition, type ValuationQuote,
} from '@/lib/market/demo-valuation';

const pos = (over: Partial<ValuationPosition> = {}): ValuationPosition => ({
    instrumentKey: 'A:ASTS', name: 'AST SpaceMobile', kind: 'accion', currency: 'USD', quantity: 10, avgCost: 50, ...over,
});
const q = (over: Partial<ValuationQuote> = {}): ValuationQuote => ({
    source: 'Finnhub', currency: 'USD', c: 60, t: Date.UTC(2026, 9, 28, 15, 30) / 1000, kind: 'live', ...over,
});

describe('valuePositions - honestidad de la valoración', () => {
    it('valora con la cotización de Finnhub: valor, PyG y % sobre el coste', () => {
        const v = valuePositions([pos()], { ASTS: q() });
        expect(v.rows[0]).toMatchObject({
            status: 'valorada', price: 60, marketValue: 600, unrealizedPnl: 100, unrealizedPct: 20, currencyBasis: 'finnhub-listado', note: null,
        });
        expect(v.totals).toEqual([{ currency: 'USD', marketValue: 600, unrealizedPnl: 100, costBasis: 500, valuedPositions: 1 }]);
        expect(v.coverage).toEqual({ valued: 1, total: 1 });
    });

    it('NUNCA usa el precio de coste como mercado: sin cotización es N/D y no suma a totales', () => {
        const v = valuePositions([pos()], {});
        expect(v.rows[0]).toMatchObject({ status: 'sin-cotizacion', price: null, marketValue: null, unrealizedPnl: null });
        expect(v.totals).toEqual([]);
        expect(v.coverage).toEqual({ valued: 0, total: 1 });
    });

    it.each([0, -3, Number.NaN, Infinity * 0])('precio %s no es cotización válida', (c) => {
        expect(valuePositions([pos()], { ASTS: q({ c }) }).rows[0].status).toBe('sin-cotizacion');
    });

    it('una cotización de Yahoo se rechaza aunque traiga precio y divisa', () => {
        const row = valuePositions([pos()], { ASTS: q({ source: 'Yahoo Finance' }) }).rows[0];
        expect(row.status).toBe('fuente-no-aprobada');
        expect(row.marketValue).toBeNull();
        expect(row.quoteLabel).toBeNull();
    });

    it('divisa: ausente o desconocida => N/D; distinta de la posición => N/D sin conversión', () => {
        const none = valuePositions([pos()], { ASTS: q({ currency: null }) }).rows[0];
        expect(none.status).toBe('divisa-no-coincide');
        expect(none.note).toContain('no se infiere del símbolo');
        const gbp = valuePositions([pos()], { ASTS: q({ currency: 'GBP' }) }).rows[0];
        expect(gbp.note).toContain('GBP');
        const mismatch = valuePositions([pos({ currency: 'EUR' })], { ASTS: q({ currency: 'USD' }) }).rows[0];
        expect(mismatch.status).toBe('divisa-no-coincide');
        expect(mismatch.note).toContain('no hay conversión');
        expect(mismatch.marketValue).toBeNull();
    });

    it('las opciones no se valoran con el precio del subyacente', () => {
        const row = valuePositions([pos({ kind: 'opcion', instrumentKey: 'O:ASTS:2026-12-18:call:50:100' })], { ASTS: q() }).rows[0];
        expect(row.status).toBe('opcion-no-valorada');
        expect(row.price).toBeNull();
    });

    it('símbolo irreconocible, no consultado y divisa sin verificar tienen su estado propio', () => {
        const v = valuePositions(
            [pos({ instrumentKey: 'X:??' }), pos({ instrumentKey: 'A:NVDA' }), pos({ instrumentKey: 'A:META' })],
            { NVDA: q(), META: q() },
            { notQueried: new Set(['NVDA']), currencyUnverified: new Set(['META']) },
        );
        expect(v.rows.map((r) => r.status)).toEqual(['sin-cotizacion', 'no-consultada', 'divisa-no-coincide']);
        expect(v.coverage).toEqual({ valued: 0, total: 3 });
    });

    it('totales por divisa, solo con lo valorado, redondeados a céntimos y ordenados', () => {
        const v = valuePositions(
            [
                pos({ instrumentKey: 'A:AAA', quantity: 3, avgCost: 0.1 }),
                pos({ instrumentKey: 'A:BBB', quantity: 3, avgCost: 0.2 }),
                pos({ instrumentKey: 'A:SAN', currency: 'EUR', quantity: 100, avgCost: 4 }),
                pos({ instrumentKey: 'A:ZZZ' }), // sin cotización: no entra
            ],
            { AAA: q({ c: 0.1 }), BBB: q({ c: 0.2 }), SAN: q({ currency: 'EUR', c: 5 }) },
        );
        expect(v.totals.map((t) => t.currency)).toEqual(['EUR', 'USD']);
        expect(v.totals[0]).toMatchObject({ marketValue: 500, unrealizedPnl: 100, costBasis: 400, valuedPositions: 1 });
        expect(v.totals[1]).toMatchObject({ marketValue: 0.9, unrealizedPnl: 0, valuedPositions: 2 });
        expect(v.coverage).toEqual({ valued: 3, total: 4 });
    });

    it('coste 0: % no calculable (null) sin dividir por cero', () => {
        expect(valuePositions([pos({ avgCost: 0 })], { ASTS: q() }).rows[0].unrealizedPct).toBeNull();
    });

    it('pérdida: PyG y % negativos', () => {
        const row = valuePositions([pos()], { ASTS: q({ c: 40 }) }).rows[0];
        expect(row.unrealizedPnl).toBe(-100);
        expect(row.unrealizedPct).toBe(-20);
    });
});

describe('helpers de valoración', () => {
    it('symbolFromKey solo para acciones con símbolo', () => {
        expect(symbolFromKey('A:ASTS')).toBe('ASTS');
        expect(symbolFromKey('A:')).toBeNull();
        expect(symbolFromKey('O:ASTS:2026-12-18:call:50:100')).toBeNull();
    });
    it('resolveQuoteCurrency solo acepta EUR/USD exactos', () => {
        expect(resolveQuoteCurrency(q({ currency: ' EUR ' })).currency).toBe('EUR');
        expect(resolveQuoteCurrency(q({ currency: 'eur' })).currency).toBeNull();
        expect(resolveQuoteCurrency(q({ currency: '' })).reason).toContain('no verificada');
    });
    it('parseListingCurrencies ignora basura y normaliza símbolos', () => {
        const m = parseListingCurrencies([{ symbol: ' asts ', currency: 'USD' }, { symbol: '', currency: 'USD' }, { symbol: 'X' }, null, 5]);
        expect([...m.entries()]).toEqual([['ASTS', 'USD']]);
        expect(parseListingCurrencies('no array').size).toBe(0);
    });
    it('quoteLabel: en vivo con hora de Madrid, cierre fechado, cierre por t y desconocido', () => {
        // 15:30 UTC el 28-oct-2026 = 16:30 en Madrid (CET tras el cambio del 25-oct).
        expect(quoteLabel(q())).toBe('16:30 (hora de Madrid) · en vivo');
        expect(quoteLabel(q({ kind: 'close', closeDate: '2026-10-27' }))).toBe('cierre del 27 oct');
        expect(quoteLabel(q({ kind: 'close', closeDate: null, t: Date.UTC(2026, 9, 27, 21, 0) / 1000 }))).toBe('último cierre, dato de 27 oct 22:00');
        expect(quoteLabel({ c: 1, t: null, kind: 'close' })).toBe('cierre de fecha desconocida');
    });
    it('valuationMatches detecta valoración caducada (cantidad, coste, divisa o filas distintas)', () => {
        const positions = [pos()];
        const v = valuePositions(positions, { ASTS: q() });
        expect(valuationMatches(v, positions)).toBe(true);
        expect(valuationMatches(v, [pos({ quantity: 11 })])).toBe(false);
        expect(valuationMatches(v, [pos({ avgCost: 51 })])).toBe(false);
        expect(valuationMatches(v, [pos({ currency: 'EUR' })])).toBe(false);
        expect(valuationMatches(v, [pos(), pos({ instrumentKey: 'A:X' })])).toBe(false);
        expect(valuationRowKey({ currency: 'EUR', instrumentKey: 'A:SAN' })).toBe('EUR|A:SAN');
    });
});
