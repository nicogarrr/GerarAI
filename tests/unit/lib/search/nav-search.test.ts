// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { navItemMatchesSearch, navSectionMatchesSearch, normalizeNavSearchTerm } from '@/lib/search/nav-search';
import type { NavItem, NavSection } from '@/lib/constants';

const item = (patch: Partial<NavItem>): NavItem => ({ label: 'Resumen', href: '/x', ...patch }) as NavItem;
const section = (patch: Partial<NavSection>): NavSection => ({ title: 'Cartera', items: [], ...patch }) as unknown as NavSection;

describe('normalizeNavSearchTerm', () => {
    it('minúsculas, sin tildes y recortado', () => {
        expect(normalizeNavSearchTerm('  Inversión Ágil ')).toBe('inversion agil');
    });
});

describe('navItemMatchesSearch', () => {
    it('«cartera» encuentra por el TÍTULO de la sección aunque el item se llame Resumen', () => {
        expect(navItemMatchesSearch(section({}), item({}), 'cartera')).toBe(true);
    });
    it('casa con etiqueta, subnavLabel y descripción, sin distinguir tildes', () => {
        expect(navItemMatchesSearch(section({}), item({ label: 'Exposición' }), 'exposicion')).toBe(true);
        expect(navItemMatchesSearch(section({}), item({ subnavLabel: 'Inteligencia' }), 'inteligencia')).toBe(true);
        expect(navItemMatchesSearch(section({}), item({ description: 'Análisis de inversión' }), 'inversion')).toBe(true);
    });
    it('término vacío lo encuentra todo; término sin coincidencia no', () => {
        expect(navItemMatchesSearch(section({}), item({}), '   ')).toBe(true);
        expect(navItemMatchesSearch(section({}), item({}), 'dividendos')).toBe(false);
    });
});

describe('navSectionMatchesSearch', () => {
    it('una sección casa si ALGÚN item (aplanado) casa', () => {
        const s = section({});
        const items = [item({ label: 'Resumen' }), item({ label: 'Alertas' })];
        expect(navSectionMatchesSearch(s, 'alertas', () => items)).toBe(true);
        expect(navSectionMatchesSearch(s, 'cartera', () => items)).toBe(true);
        expect(navSectionMatchesSearch(s, 'opciones', () => items)).toBe(false);
    });
});
