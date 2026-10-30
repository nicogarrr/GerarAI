import { describe, expect, it } from 'vitest';
import {
  MODULES,
  TABS,
  asView,
  canonicalViewUrl,
  legacyResearchRedirect,
  moduleHref,
  subrouteRedirect,
  tabHref,
  tabOfView,
  viewAnchor,
} from '@/lib/research/research-views';

describe('TABS: una fila de seis pestañas', () => {
    it('son las seis acordadas, en orden, cada una con su módulo de entrada', () => {
        expect(TABS.map((t) => t.key)).toEqual(['resumen', 'tesis', 'finanzas', 'valoracion', 'seguimiento', 'fuentes']);
        expect(TABS.map((t) => t.label)).toEqual(['Resumen', 'Tesis', 'Finanzas', 'Valoración', 'Seguimiento', 'Fuentes']);
        expect(TABS.map((t) => t.entry)).toEqual(['overview', 'thesis', 'financials', 'valuation', 'changes', 'documents']);
    });
    it('todo módulo cuelga de una pestaña existente y las entradas no llevan ancla', () => {
        const tabKeys = new Set(TABS.map((t) => t.key));
        for (const m of MODULES) expect(tabKeys.has(m.tab), `${m.key} en pestaña desconocida ${m.tab}`).toBe(true);
        for (const t of TABS) {
            const entry = MODULES.find((m) => m.key === t.entry);
            expect(entry, `entrada ${t.entry} existe`).toBeDefined();
            expect('anchor' in entry!, `entrada ${t.entry} sin ancla`).toBe(false);
            expect(entry!.tab, `entrada ${t.entry} cuelga de ${t.key}`).toBe(t.key);
        }
    });
});

describe('asView', () => {
    it('las claves de pestaña abren su módulo de entrada', () => {
        expect(asView('resumen')).toBe('overview');
        expect(asView('tesis')).toBe('thesis');
        expect(asView('finanzas')).toBe('financials');
        expect(asView('valoracion')).toBe('valuation');
        expect(asView('seguimiento')).toBe('changes');
        expect(asView('fuentes')).toBe('documents');
    });
    it('las claves de módulo abren la entrada de su pestaña', () => {
        expect(asView('thesis')).toBe('thesis');
        expect(asView('moat')).toBe('valuation');
        expect(asView('capital')).toBe('financials');
        expect(asView('terminal')).toBe('financials');
        expect(asView('noticias')).toBe('overview');
        expect(asView('holders')).toBe('changes');
        expect(asView('chat')).toBe('documents');
    });
    it('los grupos históricos siguen abriendo su módulo', () => {
        expect(asView('numeros')).toBe('financials');
        expect(asView('mas')).toBe('changes');
        expect(asView('entender')).toBe('overview');
        expect(asView('valorar')).toBe('valuation');
        expect(asView('seguir')).toBe('changes');
        expect(asView('financieros')).toBe('financials');
        expect(asView('modelo')).toBe('valuation');
        expect(asView('evidencia')).toBe('documents');
    });
    it('basura o ausente -> overview', () => {
        expect(asView(undefined)).toBe('overview');
        expect(asView('')).toBe('overview');
        expect(asView('__proto__')).toBe('overview');
        expect(asView('constructor')).toBe('overview');
    });
});

describe('tabHref / moduleHref / viewAnchor / tabOfView', () => {
    it('la pestaña Resumen es la ficha desnuda; el resto, ?view=', () => {
        expect(tabHref('AAPL', 'resumen')).toBe('/research/AAPL');
        expect(tabHref('BRK/B', 'finanzas')).toBe('/research/BRK%2FB?view=finanzas');
    });
    it('el módulo apunta a su pestaña, con ancla si es sección', () => {
        const thesis = MODULES.find((m) => m.key === 'thesis')!;
        const moat = MODULES.find((m) => m.key === 'moat')!;
        const capital = MODULES.find((m) => m.key === 'capital')!;
        const overview = MODULES.find((m) => m.key === 'overview')!;
        expect(moduleHref('AAPL', thesis)).toBe('/research/AAPL?view=tesis');
        expect(moduleHref('AAPL', moat)).toBe('/research/AAPL?view=valoracion#foso');
        expect(moduleHref('AAPL', capital)).toBe('/research/AAPL?view=finanzas#dilucion');
        expect(moduleHref('AAPL', overview)).toBe('/research/AAPL');
    });
    it('viewAnchor y tabOfView reflejan el mapa', () => {
        expect(viewAnchor('moat')).toBe('foso');
        expect(viewAnchor('thesis')).toBeUndefined();
        expect(viewAnchor('valoracion')).toBeUndefined();
        expect(tabOfView('moat')).toBe('valoracion');
        expect(tabOfView('documents')).toBe('fuentes');
    });
});

describe('canonicalViewUrl: una URL por contenido', () => {
    it('sin parámetro o clave de pestaña ya es canónica', () => {
        expect(canonicalViewUrl('AAPL', undefined)).toBeNull();
        expect(canonicalViewUrl('AAPL', 'finanzas')).toBeNull();
        expect(canonicalViewUrl('AAPL', 'valoracion')).toBeNull();
    });
    it('las claves de módulo redirigen a su pestaña con ancla', () => {
        expect(canonicalViewUrl('AAPL', 'moat')).toBe('/research/AAPL?view=valoracion#foso');
        expect(canonicalViewUrl('AAPL', 'thesis')).toBe('/research/AAPL?view=tesis');
        expect(canonicalViewUrl('AAPL', 'overview')).toBe('/research/AAPL');
        expect(canonicalViewUrl('AAPL', 'noticias')).toBe('/research/AAPL#noticias');
    });
    it('los grupos históricos redirigen a su pestaña', () => {
        expect(canonicalViewUrl('AAPL', 'numeros')).toBe('/research/AAPL?view=finanzas');
        expect(canonicalViewUrl('AAPL', 'mas')).toBe('/research/AAPL?view=seguimiento');
        expect(canonicalViewUrl('AAPL', 'valorar')).toBe('/research/AAPL?view=valoracion#modelo');
    });
    it('claves desconocidas no redirigen: caen en la vista general', () => {
        expect(canonicalViewUrl('AAPL', 'no-existe')).toBeNull();
        expect(canonicalViewUrl('AAPL', '__proto__')).toBeNull();
    });
});

describe('subrouteRedirect', () => {
    it('las subrutas históricas llevan a su sección', () => {
        expect(subrouteRedirect('AAPL', 'financial-terminal')).toBe('/research/AAPL?view=finanzas#terminal');
        expect(subrouteRedirect('AAPL', 'share-capital')).toBe('/research/AAPL?view=finanzas#dilucion');
        expect(subrouteRedirect('AAPL', 'driver-assumptions')).toBe('/research/AAPL?view=valoracion#supuestos');
        expect(subrouteRedirect('AAPL', 'management-credibility')).toBe('/research/AAPL?view=seguimiento#directiva');
        expect(subrouteRedirect('AAPL', 'decision-lessons')).toBe('/research/AAPL?view=seguimiento#lecciones');
        expect(subrouteRedirect('AAPL', 'news')).toBeNull();
    });
});


describe('legacy research middleware routes', () => {
    it.each(['assistant', 'news', 'sources'])('never redirects the static %s route', (route) => {
        expect(legacyResearchRedirect(`/research/${route}`, '?view=thesis')).toBeNull();
        expect(legacyResearchRedirect(`/research/${route}/share-capital`, '?view=terminal')).toBeNull();
    });
    it('continues redirecting a company legacy view', () => {
        expect(legacyResearchRedirect('/research/AAPL', '?view=thesis')).toBe('/research/AAPL?view=tesis');
    });
});

describe('legacyResearchRedirect con URL mal codificada', () => {
  it('no lanza con un % mal formado (el middleware daría 500)', () => {
    expect(() => legacyResearchRedirect('/research/%E0', '?view=thesis')).not.toThrow();
    expect(legacyResearchRedirect('/research/%E0', '?view=thesis')).toBeNull();
    expect(legacyResearchRedirect('/research/%E0/share-capital', '')).toBeNull();
  });
});
