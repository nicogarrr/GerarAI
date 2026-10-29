import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { asView, moduleHref, GROUPS, MODULES, type View } from '../lib/research/research-views.ts';

describe('ficha en 3 pestañas + Más: mapeo de vistas', () => {
    it('las pestañas abren su módulo de entrada', () => {
        assert.equal(asView('resumen'), 'overview');
        assert.equal(asView('numeros'), 'financials');
        assert.equal(asView('fuentes'), 'documents');
        assert.equal(asView('mas'), 'changes');
        assert.equal(GROUPS.length, 4);
        assert.deepEqual(GROUPS.map((g) => g.label), ['Resumen', 'Números', 'Fuentes', 'Más']);
    });
    it('los 3 pasos anteriores (Entender/Valorar/Seguir) siguen abriendo lo mismo', () => {
        assert.equal(asView('entender'), 'overview');
        assert.equal(asView('valorar'), 'model');
        assert.equal(asView('seguir'), 'changes');
    });
    it('cada módulo cuelga de la pestaña acordada', () => {
        const groupOf = (key: string) => MODULES.find((m) => m.key === key)?.group;
        for (const key of ['overview', 'thesis', 'noticias']) assert.equal(groupOf(key), 'resumen');
        for (const key of ['financials', 'valuation', 'model', 'peers', 'moat', 'capital', 'terminal']) assert.equal(groupOf(key), 'numeros');
        for (const key of ['documents', 'sources', 'chat']) assert.equal(groupOf(key), 'fuentes');
        for (const key of ['changes', 'holders', 'lecciones', 'directiva', 'satellites', 'supuestos', 'market-opportunity']) assert.equal(groupOf(key), 'mas');
        assert.equal(MODULES.filter((m) => m.group === 'numeros').length, 7);
    });
    it('las 6 claves de grupo antiguas siguen abriendo su módulo', () => {
        assert.equal(asView('resumen'), 'overview');
        assert.equal(asView('tesis'), 'thesis');
        assert.equal(asView('financieros'), 'financials');
        assert.equal(asView('modelo'), 'model');
        assert.equal(asView('evidencia'), 'documents');
        assert.equal(asView('seguimiento'), 'changes');
    });
    it('cada módulo ?view= se abre a sí mismo y las subrutas caen a overview', () => {
        const views = MODULES.filter((m) => !('path' in m));
        const subs = MODULES.filter((m) => 'path' in m);
        assert.equal(views.length, 15);
        assert.equal(subs.length, 5);
        for (const m of views) assert.equal(asView(m.key), m.key);
        for (const m of subs) assert.equal(asView(m.key), 'overview');
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
    it('todo módulo cuelga de un paso existente y su href es el esperado', () => {
        const groupKeys = new Set(GROUPS.map((g) => g.key));
        for (const m of MODULES) {
            assert.ok(groupKeys.has(m.group), `${m.key} en paso desconocido ${m.group}`);
            const href = moduleHref('AAPL', m);
            assert.equal(href, 'path' in m ? `/research/AAPL/${m.path}` : `/research/AAPL?view=${m.key}`);
        }
    });

    it('el resumen omite la tarjeta de metadatos y conserva acceso al modelo completo', () => {
        const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
        const overviewStart = page.indexOf("if (activeView === 'overview') {");
        const overviewEnd = page.indexOf("} else if (activeView === 'thesis')", overviewStart);
        assert.ok(overviewStart > 0 && overviewEnd > overviewStart, 'región overview identificada');
        const overview = page.slice(overviewStart, overviewEnd);
        assert.doesNotMatch(overview, /title="Modelo fundamental a largo plazo"/, 'no restaurar la tarjeta redundante');
        assert.doesNotMatch(overview, /model_summary\.(framework_key|engine_version|horizon_years)/, 'metadatos internos fuera del resumen');
        assert.match(overview, /<Link[^>]+href=\{`[^`]+\?view=model`\}[^>]*>\{snapshot\.model_summary\.publishable \? 'publicable' : 'bloqueado'\}<\/Link>/, 'el estado sigue enlazando al modelo');
        const modelStart = page.indexOf("} else if (activeView === 'model')");
        const modelEnd = page.indexOf("} else if (activeView === 'market-opportunity')", modelStart);
        assert.ok(modelStart > overviewEnd && modelEnd > modelStart, 'vista Modelo identificada');
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
