import { describe, expect, it } from 'vitest';
import { researchRelevanceKey, sortCompaniesByRelevance } from '@/lib/research/relevance';

const pf = new Set(['MSFT']);
const wl = new Set(['NVDA']);

describe('researchRelevanceKey', () => {
    it('tesis > cartera > watchlist > resto, con ticker normalizado', () => {
        expect(researchRelevanceKey('zzz', true, pf, wl)).toBe(0);
        expect(researchRelevanceKey(' msft ', false, pf, wl)).toBe(1);
        expect(researchRelevanceKey('nvda', false, pf, wl)).toBe(2);
        expect(researchRelevanceKey('AAPL', false, pf, wl)).toBe(3);
    });
    it('una posición en cartera con tesis sigue en el primer grupo', () => {
        expect(researchRelevanceKey('MSFT', true, pf, wl)).toBe(0);
    });
});

describe('sortCompaniesByRelevance', () => {
    const companies = [{ ticker: 'AAPL' }, { ticker: 'NVDA' }, { ticker: 'MSFT' }, { ticker: 'TSLA' }, { ticker: 'ABB' }];
    it('ordena por grupo y desempata por ticker; no muta la entrada', () => {
        const copy = [...companies];
        const out = sortCompaniesByRelevance(companies, (c) => c.ticker === 'TSLA', pf, wl);
        expect(out.map((c) => c.ticker)).toEqual(['TSLA', 'MSFT', 'NVDA', 'AAPL', 'ABB'].sort((a, b) => 0) && ['TSLA', 'MSFT', 'NVDA', 'AAPL', 'ABB'].slice(0, 3).concat(['AAPL', 'ABB'].sort()));
        expect(companies).toEqual(copy);
    });
    it('lista vacía', () => {
        expect(sortCompaniesByRelevance([], () => false, pf, wl)).toEqual([]);
    });
});
