import { describe, expect, it } from 'vitest';
import { GROUPS, MODULES, asView, moduleHref } from '@/lib/research/research-views';

describe('asView', () => {
    it('módulo válido sin ruta propia se acepta', () => {
        expect(asView('thesis')).toBe('thesis');
        expect(asView('holders')).toBe('holders');
    });
    it('módulos con ruta propia (capital, terminal...) no son vista: caen a overview', () => {
        expect(asView('capital')).toBe('overview');
        expect(asView('terminal')).toBe('overview');
    });
    it('grupos llevan a su entrada; enlaces antiguos siguen funcionando', () => {
        expect(asView('numeros')).toBe('financials');
        expect(asView('mas')).toBe('changes');
        expect(asView('valorar')).toBe('model');
        expect(asView('seguimiento')).toBe('changes');
    });
    it('basura o ausente -> overview', () => {
        expect(asView(undefined)).toBe('overview');
        expect(asView('')).toBe('overview');
        expect(asView('__proto__')).toBe('overview');
        expect(asView('constructor')).toBe('overview');
    });
    it('toda entrada de grupo apunta a un módulo existente', () => {
        for (const g of GROUPS) expect(MODULES.some((m) => m.key === g.entry)).toBe(true);
    });
});

describe('moduleHref', () => {
    it('vista como query; módulo con ruta como subruta; ticker codificado', () => {
        const thesis = MODULES.find((m) => m.key === 'thesis')!;
        const capital = MODULES.find((m) => m.key === 'capital')!;
        expect(moduleHref('AAPL', thesis)).toBe('/research/AAPL?view=thesis');
        expect(moduleHref('BRK/B', capital)).toBe('/research/BRK%2FB/share-capital');
    });
});
