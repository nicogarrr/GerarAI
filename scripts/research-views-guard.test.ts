import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { asView, moduleHref, GROUPS, MODULES, type View } from '../lib/research/research-views.ts';

describe('ficha en 3 pasos: mapeo de vistas', () => {
    it('los 3 pasos abren su módulo de entrada', () => {
        assert.equal(asView('entender'), 'overview');
        assert.equal(asView('valorar'), 'model');
        assert.equal(asView('seguir'), 'changes');
        assert.equal(GROUPS.length, 3);
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
        assert.equal(views.length, 14);
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

    it('los paneles del resumen van plegados por defecto en móvil (feedback Nico)', () => {
        const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
        for (const title of ['Últimas noticias', 'Última tesis', 'Modelo fundamental a largo plazo', 'Calidad financiera según la empresa', 'Últimos cambios', 'Por dónde seguir', 'Satélites AST']) {
            const i = page.indexOf(`title="${title}"`);
            assert.ok(i > 0, `panel ${title} existe`);
            const openTag = page.slice(page.lastIndexOf('<Panel', i), i);
            assert.ok(openTag.includes('collapsible="mobile"'), `panel ${title} plegable en móvil`);
        }
    });
});
