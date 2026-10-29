import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { MODULES, TABS, asView, canonicalViewUrl, moduleHref, subrouteRedirect, tabHref, type View } from '../lib/research/research-views.ts';

describe('ficha en una fila de seis pestañas: mapeo de vistas', () => {
    it('las seis pestañas abren su módulo de entrada', () => {
        assert.equal(TABS.length, 6);
        assert.deepEqual(TABS.map((t) => t.label), ['Resumen', 'Tesis', 'Finanzas', 'Valoración', 'Seguimiento', 'Fuentes']);
        assert.equal(asView('resumen'), 'overview');
        assert.equal(asView('tesis'), 'thesis');
        assert.equal(asView('finanzas'), 'financials');
        assert.equal(asView('valoracion'), 'valuation');
        assert.equal(asView('seguimiento'), 'changes');
        assert.equal(asView('fuentes'), 'documents');
    });
    it('cada módulo cuelga de la pestaña acordada', () => {
        const tabOf = (key: string) => MODULES.find((m) => m.key === key)?.tab;
        for (const key of ['overview', 'noticias']) assert.equal(tabOf(key), 'resumen');
        for (const key of ['thesis']) assert.equal(tabOf(key), 'tesis');
        for (const key of ['financials', 'terminal', 'capital']) assert.equal(tabOf(key), 'finanzas');
        for (const key of ['valuation', 'model', 'supuestos', 'market-opportunity', 'peers', 'moat']) assert.equal(tabOf(key), 'valoracion');
        for (const key of ['changes', 'holders', 'directiva', 'lecciones', 'satellites']) assert.equal(tabOf(key), 'seguimiento');
        for (const key of ['documents', 'sources', 'chat']) assert.equal(tabOf(key), 'fuentes');
        assert.equal(MODULES.length, 20);
    });
    it('las claves de módulo y los grupos históricos siguen abriendo lo suyo', () => {
        assert.equal(asView('moat'), 'valuation');
        assert.equal(asView('capital'), 'financials');
        assert.equal(asView('numeros'), 'financials');
        assert.equal(asView('mas'), 'changes');
        assert.equal(asView('entender'), 'overview');
        assert.equal(asView('valorar'), 'valuation');
        assert.equal(asView('seguir'), 'changes');
    });
    it('claves desconocidas o ausentes caen en la vista general', () => {
        assert.equal(asView(undefined), 'overview');
        assert.equal(asView(''), 'overview');
        assert.equal(asView('no-existe'), 'overview');
    });
    it('el lookup legacy no hereda del prototipo de Object', () => {
        for (const trap of ['constructor', 'toString', '__proto__', 'hasOwnProperty', 'valueOf']) {
            const v: View = asView(trap);
            assert.equal(typeof v, 'string', `${trap} no debe devolver una función heredada`);
            assert.equal(v, 'overview', `${trap} debe caer en la vista general`);
        }
        const src = readFileSync('lib/research/research-views.ts', 'utf8');
        assert.match(src, /new Map<string, View>/, 'el mapa legacy es un Map, no un Record');
    });
    it('una URL por contenido: módulos y grupos redirigen a su URL canónica', () => {
        assert.equal(canonicalViewUrl('AAPL', undefined), null);
        assert.equal(canonicalViewUrl('AAPL', 'finanzas'), null);
        assert.equal(canonicalViewUrl('AAPL', 'moat'), '/research/AAPL?view=valoracion#foso');
        assert.equal(canonicalViewUrl('AAPL', 'overview'), '/research/AAPL');
        assert.equal(canonicalViewUrl('AAPL', 'numeros'), '/research/AAPL?view=finanzas');
        assert.equal(canonicalViewUrl('AAPL', 'no-existe'), null);
        assert.equal(tabHref('AAPL', 'resumen'), '/research/AAPL');
        for (const m of MODULES) {
            const href = moduleHref('AAPL', m);
            const base = 'anchor' in m ? `${tabHref('AAPL', m.tab)}#${m.anchor}` : tabHref('AAPL', m.tab);
            assert.equal(href, base, `${m.key} tiene su URL canónica`);
        }
        for (const [sub, expected] of [
            ['financial-terminal', '/research/AAPL?view=finanzas#terminal'],
            ['share-capital', '/research/AAPL?view=finanzas#dilucion'],
            ['driver-assumptions', '/research/AAPL?view=valoracion#supuestos'],
            ['management-credibility', '/research/AAPL?view=seguimiento#directiva'],
            ['decision-lessons', '/research/AAPL?view=seguimiento#lecciones'],
        ] as const) {
            assert.equal(subrouteRedirect('AAPL', sub), expected, `${sub} redirige a su sección`);
        }
    });

    it('la página compone cada pestaña como secciones seguidas con título y ancla', () => {
        const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
        // Redirect canónico antes de resolver la vista, conservando parámetros.
        assert.match(page, /const canonicalView = canonicalViewUrl\(ticker, query\.view\);/);
        assert.match(page, /search\.set\(key, value\)/, 'conserva ?chat=, ?pagina= y los controles del terminal');
        // Las seis pestañas con sus secciones.
        for (const anchor of ['financieros', 'terminal', 'dilucion', 'valoracion', 'modelo', 'supuestos', 'oportunidad', 'comparables', 'foso', 'cambios', 'superinversores', 'directiva', 'lecciones', 'documentos', 'fuentes', 'chat']) {
            const inline = page.includes(`id: '${anchor}'`);
            const optional = page.includes(`optionalSection('${anchor}'`);
            assert.ok(inline || optional, `sección ${anchor} presente`);
        }
        // Sumario local de la pestaña: nunca otra barra global.
        assert.match(page, /aria-label="En esta página"/);
        // Las secciones no principales degradan a aviso inline, nunca a vacío.
        assert.match(page, /optionalSection\('terminal', 'Terminal financiero'/);
        assert.match(page, /<SectionLoadError retryHref=/);
    });

    it('el resumen conserva el acceso al modelo completo en su ancla canónica', () => {
        const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
        assert.match(page, /\?view=valoracion#modelo`\}[^>]*>\{snapshot\.model_summary\.publishable \? 'publicable' : 'bloqueado'\}/, 'el estado sigue enlazando al modelo');
        const modelStart = page.indexOf('const buildModelSection');
        const modelEnd = page.indexOf('const buildMarketOpportunitySection', modelStart);
        assert.ok(modelStart > 0 && modelEnd > modelStart, 'sección Modelo identificada');
        const modelView = page.slice(modelStart, modelEnd);
        assert.match(modelView, /await viewData\('model'\)/, 'sigue leyendo el modelo real');
        assert.match(modelView, /<LongTermModelPanel model=\{model\?\.status === 'not_generated' \? null : model\} ticker=\{ticker\}/, 'conserva el panel completo y su estado vacío');
        const richPanel = readFileSync('components/research/FundamentalModelPanels.tsx', 'utf8');
        assert.match(richPanel, />Modelo fundamental a largo plazo<\/h2>/, 'conserva el título en la vista rica');
        assert.match(richPanel, /model\.horizon_years/, 'conserva el horizonte');
        assert.match(richPanel, /frameworkLabel\(model\.framework\.label\)/, 'conserva el framework');
        assert.match(richPanel, /model\.publishable/, 'conserva el estado publicable');
    });

    it('los paneles del resumen van plegados por defecto en móvil (feedback Nico)', () => {
        const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
        for (const title of ['Últimas noticias', 'Calidad financiera según la empresa', 'Últimos cambios', 'Por dónde seguir', 'Satélites AST']) {
            const i = page.indexOf(`title="${title}"`);
            assert.ok(i > 0, `panel ${title} existe`);
            const openTag = page.slice(page.lastIndexOf('<Panel', i), i);
            assert.ok(openTag.includes('collapsible="mobile"'), `panel ${title} plegable en móvil`);
        }
        // «Última tesis» es lo esencial de la ficha: abierta en móvil, con veredicto y cifras clave.
        const tesis = page.indexOf('title="Última tesis"');
        assert.ok(!page.slice(page.lastIndexOf('<Panel', tesis), tesis).includes('collapsible'), 'Última tesis no se pliega');
    });
});
