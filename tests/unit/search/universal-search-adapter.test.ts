import { describe, expect, it } from 'vitest';

import { toUniversalSearchResponse, UniversalSearchContractError } from '@/lib/research/universal-search';

/**
 * El adaptador del buscador universal distingue «cero legítimo» de «contrato
 * roto» (hallazgo 2026-11-08, ref 760826059: un 200 con cuerpo inesperado
 * reventaba /search y no debe disfrazarse de «sin evidencia»).
 */
describe('toUniversalSearchResponse: formas conformes', () => {
    it('traduce la forma paginada { items, page_info }', () => {
        const item = { entity_type: 'ticker', entity_id: 1, title: 'A', text: 'B', scores: { reranker: 0.5 } };
        const out = toUniversalSearchResponse({ query: 'test', items: [item], page_info: { total_items: 7 } });
        expect(out.results).toHaveLength(1);
        expect(out.results[0].entity_type).toBe('ticker');
        expect(out.total).toBe(7);
        expect(out.retrieval).toEqual({});
    });

    it('lista vacía legítima: cero resultados SIN error', () => {
        const out = toUniversalSearchResponse({ query: 'test', items: [], page_info: { total_items: 0 } });
        expect(out).toEqual({ query: 'test', retrieval: {}, total: 0, results: [] });
    });

    it('total ausente o no numérico: cae al recuento de resultados', () => {
        const item = { entity_type: 'ticker', entity_id: 1 };
        expect(toUniversalSearchResponse({ results: [item, item] }).total).toBe(2);
        expect(toUniversalSearchResponse({ results: [item], total: Number.NaN }).total).toBe(1);
    });

    it('conserva query, status y filters conformes', () => {
        const out = toUniversalSearchResponse({ query: 'bme', status: 'ok', filters: { ticker: 'BME' }, retrieval: { mode: 'hybrid' }, total: 0, results: [] });
        expect(out.query).toBe('bme');
        expect(out.status).toBe('ok');
        expect(out.filters).toEqual({ ticker: 'BME' });
        expect(out.retrieval).toEqual({ mode: 'hybrid' });
    });
});

describe('toUniversalSearchResponse: contrato roto = error, nunca vacío falso', () => {
    it('cuerpo null / no objeto / array: UniversalSearchContractError', () => {
        expect(() => toUniversalSearchResponse(null)).toThrow(UniversalSearchContractError);
        expect(() => toUniversalSearchResponse(undefined)).toThrow(UniversalSearchContractError);
        expect(() => toUniversalSearchResponse('error')).toThrow(UniversalSearchContractError);
        expect(() => toUniversalSearchResponse([])).toThrow(UniversalSearchContractError);
    });

    it('results/items presentes pero no lista: UniversalSearchContractError', () => {
        expect(() => toUniversalSearchResponse({ items: { bad: true } })).toThrow(UniversalSearchContractError);
        expect(() => toUniversalSearchResponse({ results: 'oops' })).toThrow(UniversalSearchContractError);
    });

    it('retrieval o filters no objeto: UniversalSearchContractError', () => {
        expect(() => toUniversalSearchResponse({ retrieval: 'hybrid' })).toThrow(UniversalSearchContractError);
        expect(() => toUniversalSearchResponse({ filters: [1] })).toThrow(UniversalSearchContractError);
    });
});

describe('toUniversalSearchResponse: ítems hostiles dentro de una lista válida', () => {
    it('[null] se filtra: results queda [] y el render no puede lanzar', () => {
        const out = toUniversalSearchResponse({ items: [null], total: 1 });
        expect(out.results).toEqual([]);
    });

    it('ítem sin scores se conserva con scores a cero (el JSX lee scores.reranker)', () => {
        const out = toUniversalSearchResponse({ items: [{ entity_type: 'ticker', entity_id: 3, title: 'Sin scores' }] });
        expect(out.results).toHaveLength(1);
        expect(out.results[0].scores).toEqual({ lexical: 0, vector: 0, rrf: 0, reranker: 0 });
        expect(out.results[0].title).toBe('Sin scores');
    });

    it('ítem sin identidad de entidad se descarta; campos escalares se coercionan', () => {
        const out = toUniversalSearchResponse({ items: [
            { entity_id: 1 },
            { entity_type: 'ticker', entity_id: '7', title: 42, ticker: 9, source_trust: 'alta' },
        ] });
        expect(out.results).toEqual([]);
    });
});
