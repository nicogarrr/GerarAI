import { describe, expect, it } from 'vitest';

import { toUniversalSearchResponse } from '@/lib/research/universal-search';

/**
 * El adaptador del buscador universal NUNCA puede propagar una forma hostil:
 * cualquier respuesta no conforme degrada a lista vacía honesta (hallazgo
 * 2026-11-08, ref 760826059: un 200 con cuerpo inesperado reventaba /search).
 */
describe('toUniversalSearchResponse', () => {
    it('traduce la forma paginada { items, page_info }', () => {
        const item = { entity_type: 'ticker', entity_id: 1 } as never;
        const out = toUniversalSearchResponse({ query: 'test', items: [item], page_info: { total_items: 7 } });
        expect(out.results).toEqual([item]);
        expect(out.total).toBe(7);
        expect(out.retrieval).toEqual({});
    });

    it('cuerpo null o no objeto: lista vacía, sin excepción', () => {
        expect(toUniversalSearchResponse(null)).toEqual({ query: '', retrieval: {}, total: 0, results: [] });
        expect(toUniversalSearchResponse(undefined as never)).toEqual({ query: '', retrieval: {}, total: 0, results: [] });
    });

    it('items como objeto o null: no revienta results.map', () => {
        expect(toUniversalSearchResponse({ items: { r1: {} } as never }).results).toEqual([]);
        expect(toUniversalSearchResponse({ items: null }).results).toEqual([]);
    });

    it('results no array y retrieval string: coerce a formas seguras', () => {
        const out = toUniversalSearchResponse({ results: 'oops' as never, retrieval: 'hybrid' as never, total: Number.NaN });
        expect(out.results).toEqual([]);
        expect(out.retrieval).toEqual({});
        expect(out.total).toBe(0);
    });

    it('total ausente: cae al recuento de resultados', () => {
        expect(toUniversalSearchResponse({ results: [{} as never, {} as never] }).total).toBe(2);
    });

    it('conserva query, status y filters conformes', () => {
        const out = toUniversalSearchResponse({ query: 'bme', status: 'ok', filters: { ticker: 'BME' }, retrieval: { mode: 'hybrid' }, total: 0, results: [] });
        expect(out.query).toBe('bme');
        expect(out.status).toBe('ok');
        expect(out.filters).toEqual({ ticker: 'BME' });
        expect(out.retrieval).toEqual({ mode: 'hybrid' });
    });
});
