// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { navItemMatchesSearch, navSectionMatchesSearch, normalizeNavSearchTerm } from '@/lib/search/nav-search';

describe('normalizeNavSearchTerm', () => {
    it('minúsculas, sin tildes y recortado', () => {
        expect(normalizeNavSearchTerm('  Inversión Ágil ')).toBe('inversion agil');
    });
});

describe('navItemMatchesSearch', () => {
    it('«cartera» encuentra por el TÍTULO de la sección aunque el item se llame Resumen', () => {
        expect(navItemMatchesSearch(['Cartera', 'Resumen'], 'cartera')).toBe(true);
    });
    it('casa con etiqueta, subnavLabel y descripción, sin distinguir tildes', () => {
        expect(navItemMatchesSearch(['Exposición'], 'exposicion')).toBe(true);
        expect(navItemMatchesSearch(['Resumen', 'Inteligencia'], 'inteligencia')).toBe(true);
        expect(navItemMatchesSearch(['Resumen', '', 'Análisis de inversión'], 'inversion')).toBe(true);
    });
    it('término vacío lo encuentra todo; término sin coincidencia no', () => {
        expect(navItemMatchesSearch(['Resumen'], '   ')).toBe(true);
        expect(navItemMatchesSearch(['Resumen'], 'dividendos')).toBe(false);
    });
});

describe('navSectionMatchesSearch', () => {
    it('una sección casa si ALGÚN item (aplanado) casa', () => {
        const haystacks = [['Cartera', 'Resumen'], ['Cartera', 'Alertas']];
        expect(navSectionMatchesSearch(haystacks, 'alertas')).toBe(true);
        expect(navSectionMatchesSearch(haystacks, 'cartera')).toBe(true);
        expect(navSectionMatchesSearch(haystacks, 'opciones')).toBe(false);
    });
});
