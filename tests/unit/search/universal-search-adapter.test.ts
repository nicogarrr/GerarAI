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

    it('cuerpo objeto SIN lista real ({}, items:null): contrato roto, nunca vacío falso', () => {
        expect(() => toUniversalSearchResponse({})).toThrow(UniversalSearchContractError);
        expect(() => toUniversalSearchResponse({ query: 'test' })).toThrow(UniversalSearchContractError);
        expect(() => toUniversalSearchResponse({ items: null })).toThrow(UniversalSearchContractError);
        expect(() => toUniversalSearchResponse({ results: null })).toThrow(UniversalSearchContractError);
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
    it('[null] es corrupción de datos: contrato roto, nunca filtrado silencioso', () => {
        expect(() => toUniversalSearchResponse({ items: [null], total: 1 })).toThrow(UniversalSearchContractError);
    });

    it('ítem sin identidad de entidad: contrato roto', () => {
        expect(() => toUniversalSearchResponse({ items: [{ entity_id: 1 }] })).toThrow(UniversalSearchContractError);
        expect(() => toUniversalSearchResponse({ items: [{ entity_type: 'ticker', entity_id: '7' }] })).toThrow(UniversalSearchContractError);
    });

    it('ítem sin métricas: source_trust y scores quedan null (la ficha pinta N/D), nunca 0 inventado', () => {
        const out = toUniversalSearchResponse({ items: [{ entity_type: 'ticker', entity_id: 3, title: 'Sin métricas' }] });
        expect(out.results).toHaveLength(1);
        expect(out.results[0].source_trust).toBeNull();
        expect(out.results[0].scores).toEqual({ lexical: null, vector: null, rrf: null, reranker: null });
        expect(out.results[0].title).toBe('Sin métricas');
    });

    it('métricas presentes pero inválidas: null, no cero', () => {
        const out = toUniversalSearchResponse({ items: [{ entity_type: 'ticker', entity_id: 3, source_trust: 'alta', scores: { reranker: Number.NaN, vector: 0.2 } }] });
        expect(out.results[0].source_trust).toBeNull();
        expect(out.results[0].scores.reranker).toBeNull();
        expect(out.results[0].scores.vector).toBe(0.2);
    });
});
