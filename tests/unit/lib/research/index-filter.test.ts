import { describe, expect, it } from 'vitest';
import {
    RESEARCH_INDEX_PAGE_SIZE, filterResearchIndex, firstSearchParam, paginateResearchIndex, parseIndexPage, researchIndexHref,
} from '@/lib/research/index-filter';

const items = [{ ticker: 'AAPL', name: 'Apple Inc' }, { ticker: 'MSFT', name: 'Microsoft' }, { ticker: 'AMZN', name: undefined as unknown as string }];

describe('filterResearchIndex', () => {
    it('sin consulta devuelve todo; filtra por ticker o nombre sin mayúsculas', () => {
        expect(filterResearchIndex(items, '   ')).toBe(items);
        expect(filterResearchIndex(items, 'micro').map(i => i.ticker)).toEqual(['MSFT']);
        expect(filterResearchIndex(items, ' aa').map(i => i.ticker)).toEqual(['AAPL']);
    });
    it('nombre ausente no rompe el filtro', () => {
        expect(filterResearchIndex(items, 'amzn')).toHaveLength(1);
        expect(filterResearchIndex(items, 'zzz')).toEqual([]);
    });
});

describe('paginateResearchIndex', () => {
    const rows = Array.from({ length: 95 }, (_, i) => i);
    it('tamaño de página por defecto y límites de página', () => {
        const p1 = paginateResearchIndex(rows, 1);
        expect(p1).toMatchObject({ page: 1, pages: 3, total: 95, from: 1, to: RESEARCH_INDEX_PAGE_SIZE });
        const last = paginateResearchIndex(rows, 99);
        expect(last).toMatchObject({ page: 3, from: 81, to: 95 });
        expect(last.rows).toHaveLength(15);
        expect(paginateResearchIndex(rows, -4).page).toBe(1);
    });
    it('vacío: una página, from/to 0', () => {
        expect(paginateResearchIndex([], 5)).toEqual({ rows: [], page: 1, pages: 1, total: 0, from: 0, to: 0 });
    });
});

describe('parámetros de búsqueda', () => {
    it('firstSearchParam toma el primero de un array y vacío si no es texto', () => {
        expect(firstSearchParam(['A', 'B'])).toBe('A');
        expect(firstSearchParam(undefined)).toBe('');
        expect(firstSearchParam([])).toBe('');
        expect(firstSearchParam('x')).toBe('x');
    });
    it('parseIndexPage cae a 1 con basura, 0, negativos; trunca decimales', () => {
        expect(parseIndexPage(undefined)).toBe(1);
        expect(parseIndexPage('abc')).toBe(1);
        expect(parseIndexPage('0')).toBe(1);
        expect(parseIndexPage('-3')).toBe(1);
        expect(parseIndexPage('Infinity')).toBe(1);
        expect(parseIndexPage('2.9')).toBe(2);
    });
    it('researchIndexHref conserva filtro y escapa', () => {
        expect(researchIndexHref('', 1)).toBe('/research');
        expect(researchIndexHref(' a b&c ', 1)).toBe('/research?q=a+b%26c');
        expect(researchIndexHref('', 3)).toBe('/research?page=3');
        expect(researchIndexHref('x', 2)).toBe('/research?q=x&page=2');
    });
});
