import { describe, expect, it } from 'vitest';
import {
    firstSearchParam, normalizeSourcesQuery, normalizeSourcesScope, normalizeSourcesTicker, normalizeSourcesType, sourcesHref, sourcesPageInfo,
} from '@/lib/research/sources-inventory';

describe('normalizadores', () => {
    it('scope: solo "all" amplía; cualquier otra cosa vuelve a "followed"', () => {
        expect(normalizeSourcesScope(' ALL ')).toBe('all');
        expect(normalizeSourcesScope('everything')).toBe('followed');
        expect(normalizeSourcesScope('')).toBe('followed');
    });
    it('tipo: minúsculas, solo [a-z0-9_] y tope de 80', () => {
        expect(normalizeSourcesType(' SEC-Filing; DROP ')).toBe('secfilingdrop');
        expect(normalizeSourcesType('a'.repeat(200))).toHaveLength(80);
    });
    it('consulta: colapsa espacios y acota a 120', () => {
        expect(normalizeSourcesQuery('  a \n  b\t c ')).toBe('a b c');
        expect(normalizeSourcesQuery('x'.repeat(300))).toHaveLength(120);
    });
    it('ticker en mayúsculas', () => {
        expect(normalizeSourcesTicker(' brk.b ')).toBe('BRK.B');
    });
});

describe('sourcesPageInfo', () => {
    it('vacío, página intermedia y fuera de rango', () => {
        expect(sourcesPageInfo(0, 3)).toEqual({ page: 1, pages: 1, from: 0, to: 0 });
        expect(sourcesPageInfo(120, 2)).toEqual({ page: 2, pages: 3, from: 51, to: 100 });
        expect(sourcesPageInfo(120, 99)).toEqual({ page: 3, pages: 3, from: 101, to: 120 });
        expect(sourcesPageInfo(120, -1).page).toBe(1);
    });
});

describe('sourcesHref', () => {
    it('sin nada: URL limpia', () => {
        expect(sourcesHref('', 1)).toBe('/research/sources');
    });
    it('conserva ticker normalizado, filtros y página >1; la consulta se normaliza', () => {
        const href = sourcesHref(' aapl ', 2, { scope: 'all', sourceType: 'filing', q: ' a   b ' });
        const params = new URLSearchParams(href.split('?')[1]);
        expect(params.get('ticker')).toBe('AAPL');
        expect(params.get('scope')).toBe('all');
        expect(params.get('source_type')).toBe('filing');
        expect(params.get('q')).toBe('a b');
        expect(params.get('page')).toBe('2');
    });
    it('consulta solo espacios no genera q', () => {
        expect(sourcesHref('X', 1, { q: '   ' })).toBe('/research/sources?ticker=X');
    });
});

describe('firstSearchParam', () => {
    it('primer valor de un array, vacío si no es texto', () => {
        expect(firstSearchParam(['a', 'b'])).toBe('a');
        expect(firstSearchParam(undefined)).toBe('');
        expect(firstSearchParam('z')).toBe('z');
    });
});
